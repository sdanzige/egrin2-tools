#!/usr/bin/env python

import argparse
import os
import sqlite3
import logging
import gzip
import pandas as pd
import requests
from datetime import datetime

"""
This merger tool outfactors the merging process, and merges into
sqlite instead to reduce dependency
"""

DESCRIPTION = """merger.py - merge cmonkey2 ensemble runs"""
LOG_FORMAT = '%(asctime)s %(levelname)-8s %(message)s'
LOG_LEVEL = logging.DEBUG
LOG_FILE = None


def is_valid_db(dbpath):
    conn = sqlite3.connect(dbpath)
    cur = conn.cursor()
    try:
        cur.execute('select finish_time from run_infos')
        row = cur.fetchone()
        return row is not None and row[0] is not None
    except:
        logging.error("incomplete run")
        return False
    finally:
        cur.close()
        conn.close()


def extract_ncbi_code(dbpath):
    conn = sqlite3.connect(dbpath)
    cur = conn.cursor()
    try:
        cur.execute('select ncbi_code from run_infos')
        return cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()


def standardize_ratios(ratios):
    """compute standardized ratios (global). row standardized"""
    ratios_standardized = ratios.copy()
    zscore = lambda x: (x - x.mean()) / x.std()

    for row in ratios.iterrows():
        ratios_standardized.loc[row[0]] = zscore(row[1])

    return ratios_standardized


def read_ratios(path):
    """reads the specified gene expression and returns both
    raw matrix and standardized matrix"""
    ratios = pd.read_csv(gzip.open(path, 'rb'), index_col=0, sep="\t")

    if ratios.shape[1] == 0:  # attempt using comma as a delimiter if tab failed
        ratios = pd.read_csv(gzip.open(path, 'rb'), index_col=0, sep=",")

    if ratios.shape[1] == 0:
        raise Exception("Cannot read ratios file. Check delimiter. Should be '\t' or ',' ")
    return ratios, standardize_ratios(ratios)


def create_tables(conn):
    """Create tables in the result database"""
    conn.execute('create table if not exists rows (name text)')
    conn.execute('create table if not exists row_annotations (name text)')
    conn.execute('create table if not exists row_annotation_values (row_id int, annot_id int, value text)')

    conn.execute('create table if not exists columns (name text)')
    conn.execute('create table if not exists col_annotations (name text)')
    conn.execute('create table if not exists col_annotation_values (col_id int, annot_id int, value text)')

    # holds both original and standardized values
    conn.execute('create table if not exists expr_values (row_id int,col_id,value decimal,std_value decimal)')

    # information about individual ensemble runs
    conn.execute('create table if not exists ensemble_runs (date_added timestamp,start_time timestamp,finish_time timestamp,num_iterations int,organism text,species text,num_rows int,num_columns,num_clusters int,git_sha text)')
    conn.execute('create table if not exists ensemble_run_rows (run_id int, row_id int)')
    conn.execute('create table if not exists ensemble_run_cols (run_id int, col_id int)')

    # bicluster information
    conn.execute('create table if not exists biclusters (run_id int, cluster_num int, residual decimal)')
    conn.execute('create table if not exists bicluster_rows (cluster_id int, row_id int)')
    conn.execute('create table if not exists bicluster_cols (cluster_id int, col_id int)')

    conn.execute('create table if not exists motif_infos (cluster_id int, seqtype text, motif_num int, evalue decimal)')
    conn.execute('create table if not exists motif_pssm_rows (motif_info_id int, row int, a decimal, c decimal, g decimal, t decimal)')
    conn.execute('create table if not exists meme_motif_sites (motif_info_id int, seq_name text, reverse boolean, start int, pvalue decimal)')

    # indexes
    conn.execute('create index if not exists rows_idx on rows (name)')
    conn.execute('create index if not exists row_annotations_idx on row_annotations (name)')

    conn.execute('create index if not exists cols_idx on columns (name)')
    conn.execute('create index if not exists col_annotations_idx on col_annotations (name)')

    conn.execute('create index if not exists expr_values_idx on expr_values (row_id,col_id)')


def annotate_microbes_online(conn, row2id, ncbi_code):
    """add all microbes online columns as an attribute to the row"""
    resp = requests.get("http://www.microbesonline.org/cgi-bin/genomeInfo.cgi?tId=%d;export=tab" % ncbi_code)
    content = [line.split('\t') for line in resp.text.split('\n')]
    titles = content[0]
    sysname_col = titles.index('sysName')
    print "sys name column at index: ", sysname_col
    
    # insert the attributes
    attr2id = {}
    cursor = conn.cursor()
    try:
        for attribute in [title for title in titles if title != 'sysName']:
            cursor.execute('insert into row_annotations (name) values (?)', [attribute])
            attr2id[attribute] = cursor.lastrowid

        for line in content[1:]:
            if len(line) < sysname_col + 1:  # line too short ?
                continue
            sysname = line[sysname_col]
            if sysname in row2id:
                row_pk = row2id[sysname]
                for col_idx in range(len(line)):
                    value = line[col_idx].strip()
                    if col_idx != sysname_col and len(value) > 0:
                        attr_id = attr2id[titles[col_idx]]
                        cursor.execute("insert into row_annotation_values (row_id,annot_id,value) values (?,?,?)", [row2id[sysname], attr_id, line[col_idx]])
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        cursor.close()    


def db_insert_rows(conn, rows):
    cursor = conn.cursor()
    result = {}
    for row in rows:
        cursor.execute('insert into rows (name) values (?)', [row])
        result[row] = cursor.lastrowid
    conn.commit()
    return result


def db_insert_cols(conn, cols):
    cursor = conn.cursor()
    result = {}
    for col in cols:
        cursor.execute('insert into columns (name) values (?)', [col])
        result[col] = cursor.lastrowid
    conn.commit()
    return result


def store_ratios(conn, raw_ratios, std_ratios, row2id, col2id):
    """Store gene expressions"""
    logging.info("Storing gene expressions...")
    num_rows = 0
    for rowidx, rowname in enumerate(raw_ratios.index.values):
        if num_rows % 200 == 0:
            logging.info("%.2f percent done (%d rows)",
                         round((float(num_rows) / raw_ratios.shape[0]) * 100, 1), num_rows)
        row_pk = row2id[rowname]
        for colidx, colname in enumerate(raw_ratios.columns.values):
            col_pk = col2id[colname]
            raw_value = raw_ratios.values[rowidx, colidx]
            std_value = std_ratios.values[rowidx, colidx]
            conn.execute('insert into expr_values (row_id,col_id,value,std_value) values (?,?,?,?)',
                         [row_pk, col_pk, raw_value, std_value])
        num_rows += 1

    conn.commit()
    logging.info("done.")


def store_run_info(conn, src_conn, row2id, col2id):
    """Stores the information about an individual ensemble run in the database"""
    logging.info("Store individual run information...")
    src_cur = src_conn.cursor()
    cursor = conn.cursor()
    try:
        src_cur.execute('select start_time,finish_time,num_iterations,organism,species,num_rows,num_columns,num_clusters,git_sha from run_infos')
        run_info = src_cur.fetchone()
        cursor.execute('insert into ensemble_runs (date_added,start_time,finish_time,num_iterations,organism,species,num_rows,num_columns,num_clusters,git_sha) values (?,?,?,?,?,?,?,?,?,?)',
                        [datetime.now(), run_info[0], run_info[1], run_info[2],
                        run_info[3], run_info[4], run_info[5], run_info[6],
                        run_info[7], run_info[8]])
        run_id = cursor.lastrowid
        src_cur.execute('select name from row_names')
        row_names = [row[0] for row in src_cur.fetchall()]
        src_cur.execute('select name from column_names')
        col_names = [row[0] for row in src_cur.fetchall()]
        for rowname in row_names:
            cursor.execute('insert into ensemble_run_rows (run_id,row_id) values (?,?)',
                           [run_id, row2id[rowname]])
        for colname in col_names:
            cursor.execute('insert into ensemble_run_cols (run_id,col_id) values (?,?)',
                           [run_id, col2id[colname]])

        conn.commit()
        return run_id
    finally:
        cursor.close()
        src_cur.close()


def store_biclusters(conn, src_conn, run_id, row2id, col2id):
    """copy bicluster information for the specified run"""
    logging.info("copying biclusters...")
    src_cursor = src_conn.cursor()
    src_cursor2 = src_conn.cursor()
    cursor = conn.cursor()
    cluster2id = {}
    try:
        src_cursor.execute('select max(iteration) from cluster_stats')
        last_iter = src_cursor.fetchone()[0]
        src_cursor.execute('select cluster,residual from cluster_stats where iteration=?',
                           [last_iter])
        for cluster, residual in src_cursor.fetchall():
            src_cursor2.execute('select name from row_members rm join row_names rn on rm.order_num=rn.order_num where rm.iteration=? and rm.cluster=?', [last_iter, cluster])
            rownames = [row[0] for row in src_cursor2.fetchall()]
            src_cursor2.execute('select name from column_members cm join column_names cn on cm.order_num=cn.order_num where cm.iteration=? and cm.cluster=?', [last_iter, cluster])
            colnames = [row[0] for row in src_cursor2.fetchall()]

            cursor.execute('insert into biclusters (run_id,cluster_num,residual) values (?,?,?)',
                           [run_id, cluster, residual])
            cluster_id = cursor.lastrowid
            cluster2id[cluster] = cluster_id

            for rowname in rownames:
                cursor.execute('insert into bicluster_rows (cluster_id,row_id) values (?,?)',
                               [cluster_id, row2id[rowname]])
            for colname in colnames:
                cursor.execute('insert into bicluster_cols (cluster_id,col_id) values (?,?)',
                               [cluster_id, col2id[colname]])

        conn.commit()
        return cluster2id
    finally:
        cursor.close()
        src_cursor.close()
        src_cursor2.close()


def store_motifs(conn, src_conn, cluster2id):
    src_cursor = src_conn.cursor()
    src_cursor2 = src_conn.cursor()
    cursor = conn.cursor()
    try:
        src_cursor.execute('select max(iteration) from cluster_stats')
        last_iter = src_cursor.fetchone()[0]
        src_cursor.execute('select rowid,cluster,seqtype,motif_num,evalue from motif_infos where iteration=?', [last_iter])
        for motif_info_id, cluster, seqtype, motif_num, evalue in src_cursor.fetchall():
            cursor.execute('insert into motif_infos (cluster_id,seqtype,motif_num,evalue) values (?,?,?,?)', [cluster2id[cluster], seqtype, motif_num, evalue])
            motif_id = cursor.lastrowid

            # PSSMs
            src_cursor2.execute('select row,a,c,g,t from motif_pssm_rows where motif_info_id=? order by row', [motif_info_id])
            for row, a, c, g, t in src_cursor2.fetchall():
                cursor.execute('insert into motif_pssm_rows (motif_info_id,row,a,c,g,t) values (?,?,?,?,?,?)', [motif_id, row, a, c, g, t])

            # Sites
            src_cursor2.execute('select seq_name,reverse,start,pvalue from meme_motif_sites where motif_info_id=?', [motif_info_id])
            for seqname, reverse, start, pvalue in src_cursor2.fetchall():
                cursor.execute('insert into meme_motif_sites (motif_info_id,seq_name,reverse,start,pvalue) values (?,?,?,?,?)', [motif_id, seqname, reverse, start, pvalue])

        conn.commit()
    finally:
        src_cursor.close()
        src_cursor2.close()
        cursor.close()


def merge(args):
    conn = sqlite3.connect(args.targetdb, 15, isolation_level='DEFERRED')
    #conn = sqlite3.connect(args.targetdb)
    try:
        create_tables(conn)
        cmonkey_dbs = filter(is_valid_db, args.result_dbs)
        if len(cmonkey_dbs) > 0:
            ncbi_code = extract_ncbi_code(cmonkey_dbs[0])
            print "NCBI code: ", ncbi_code
            raw_ratios, std_ratios = read_ratios(args.ratios)
            row2id = db_insert_rows(conn, raw_ratios.index.values)
            col2id = db_insert_cols(conn, raw_ratios.columns.values)
            annotate_microbes_online(conn, row2id, ncbi_code)
            store_ratios(conn, raw_ratios, std_ratios, row2id, col2id)

            for cmonkey_db in cmonkey_dbs:
                src_conn = sqlite3.connect(cmonkey_db)
                try:
                    run_id = store_run_info(conn, src_conn, row2id, col2id)
                    cluster2id = store_biclusters(conn, src_conn, run_id, row2id, col2id)
                    store_motifs(conn, src_conn, cluster2id)
                finally:
                    src_conn.close()
        else:
            raise Exception('no input databases provided !!!')
    finally:
        conn.close()

if __name__ == '__main__':
    logging.basicConfig(format=LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S',
                        level=LOG_LEVEL, filename=LOG_FILE)

    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--organism', required=True, type=str,
                        help="3 letter organism code")
    parser.add_argument('--ratios', required=True)
    parser.add_argument('--targetdb', required=True)
    parser.add_argument('result_dbs', nargs='*')
    args = parser.parse_args()
    merge(args)


    
"""Mongo ColInfo
{
    "_id" : ObjectId("558c770c77ffbc5e8711b198"),
"col_id" : 19,
"egrin2_col_name" : "H37Rv..Youman.media.replicate.4",
"additional_info" : [ ]
}
"""
"""Mongo Corem
{
  "_id" : ObjectId("558c79f277ffbc5e87859004"),
  "rows" : [  3219,  3461,  3462 ],
  "density" : 1,
  "corem_id" : 20,
  "cols" : [ ],
  "edges" : [  "3219-3462",  "3219-3461",  "3462-3461" ],
  "weighted_density" : 0.03213
}
"""
"""Mongo genome: is DNA sequence"""
"""Mongo motif info
{
  "_id" : ObjectId("558c783777ffbc5e877ab78e"),
  "meme_motif_site" : [
    {
      "start" : 86,
      "row_id" : 1602,
      "scaffoldId" : 7022,
      "reverse" : 0,
      "pvalue" : 8.05e-7
    },
    {
      "start" : 50,
      "row_id" : 511,
      "scaffoldId" : 7022,
      "reverse" : 0,
      "pvalue" : 0.00000189
    },
    {
      "start" : 63,
      "row_id" : 289,
      "scaffoldId" : 7022,
      "reverse" : 1,
      "pvalue" : 0.0000271
    },
    {
      "start" : 78,
      "row_id" : 49,
      "scaffoldId" : 7022,
      "reverse" : 0,
      "pvalue" : 0.0000316
    },
    {
      "start" : 59,
      "row_id" : 1121,
      "scaffoldId" : 7022,
      "reverse" : 0,
      "pvalue" : 0.0000356
    },
    {
      "start" : 87,
      "row_id" : 2172,
      "scaffoldId" : 7022,
      "reverse" : 1,
      "pvalue" : 0.0000744
    },
    {
      "start" : 67,
      "row_id" : 2214,
      "scaffoldId" : 7022,
      "reverse" : 0,
      "pvalue" : 0.000197
    }
  ],
  "evalue" : 1900,
  "gre_id" : "NaN",
  "cluster_id" : ObjectId("558c781077ffbc5e877ab57a"),
  "motif_num" : 2,
  "seqtype" : "upstream",
  "pwm" : [
    { "a" : 0.857143, "c" : 0, "t" : 0.142857, "g" : 0, "row" : 0 },
    { "a" : 0.714286, "c" : 0, 	"t" : 0.285714, "g" : 0, "row" : 1 },
    { "a" : 0.571429, 	"c" : 0, "t" : 0.428571, "g" : 0,"row" : 2 },
    { "a" : 0, "c" : 0.285714, "t" : 0.142857, "g" : 0.571429, "row" : 3 },
    { 	"a" : 0, 	"c" : 0, 	"t" : 0, 	"g" : 1, "row" : 4 }, 	{ 	"a" : 0.142857, 	"c" : 0, 	"t" : 0.428571, 	"g" : 0.428571, 	"row" : 5 }, 	{ 	"a" : 0.142857, 	"c" : 0.714286, 	"t" : 0, 	"g" : 0.142857, 	"row" : 6 }, 	{ 	"a" : 0, 	"c" : 0, 	"t" : 0.714286, 	"g" : 0.285714, 	"row" : 7 }, 	{ 	"a" : 1, 	"c" : 0, 	"t" : 0, 	"g" : 0, 	"row" : 8 }, 	{ 	"a" : 0, "c" : 0.857143, 	"t" : 0, 	"g" : 0.142857, 	"row" : 9 } ] }
"""
"""Mongo rowrow
{ "_id" : ObjectId("558c798177ffbc5e877acd5e"), "row_ids" : [  238,  3779 ], "counts" : 2, "backbone_pval" : 0.17728185409972097, "weight" : 0.009950248756218905 }
"""
