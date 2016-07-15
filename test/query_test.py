#!/usr/bin/env python3
import sys
import unittest
import xmlrunner
import mongomock
import pandas
import numpy as np

import query.egrin2_query as e2q

ROW_INFO_FIELDS = ['row_id', 'name', 'egrin2_row_name', 'GI', 'accession', 'sysName']
MONGO_ROW_INFOS = [
    {'name': 'Rv1180', 'row_id': 1179, 'egrin2_row_name': 'e2rname1', 'GI': 234.0, 'accession': 'NP_218441.1', 'sysName': 'sys1'},
    {'name': 'Rv1181', 'row_id': 1180, 'egrin2_row_name': 'e2rname2', 'GI': 456.0, 'accession': 'NP_218442.1', 'sysName': 'sys2'}
]

MONGO_ROW_INFOS_AMBIGUOUS = [
    {'name': 'Rv1180', 'row_id': 1179, 'egrin2_row_name': 'e2rname1', 'GI': 234.0, 'accession': 'NP_218441.1', 'sysName': 'multimatch'},
    {'name': 'Rv1181', 'row_id': 1180, 'egrin2_row_name': 'e2rname2', 'GI': 456.0, 'accession': 'NP_218442.1', 'sysName': 'multimatch'}
]

class QueryTest(unittest.TestCase):  # pylint: disable-msg=R0904
    """Test suite for the egrin2_query module"""
    def setUp(self):
        self.db = mongomock.MongoClient().db
        self.db_ambiguous = mongomock.MongoClient().db
        self.db.row_info.insert_many(MONGO_ROW_INFOS)
        self.db_ambiguous.row_info.insert_many(MONGO_ROW_INFOS_AMBIGUOUS)

    def test_remove_list_duplicates(self):
        self.assertEquals([1, 2, 3], e2q.remove_list_duplicates([1, 2, 3]))
        self.assertEquals([1, 2, 3], e2q.remove_list_duplicates([1, 2, 3, 1, 2, 3]))

    def test_rsd(self):
        # don't care for empty list
        #self.assertTrue(np.isnan(e2q.rsd([])))
        self.assertEquals(0, e2q.rsd([1]))
        self.assertEquals(1/3, e2q.rsd([1, 2]))

    def test_find_match(self):
        df = pandas.DataFrame([[42, 621, 53], [14, 244, 621]], index=['row 1', 'row 2'], columns=['col 1', 'col 2', 'col 3'])
        self.assertEquals(42, e2q.find_match(42, df, 'col 1'))
        self.assertEquals(53, e2q.find_match(42, df, 'col 3'))
        self.assertEquals(244, e2q.find_match(14, df, 'col 2'))
        self.assertEquals(53, e2q.find_match(621, df, 'col 3'))
        self.assertEquals(None, e2q.find_match(4711, df, 'col 3'))

    def test_row2id_by_name(self):
        self.assertEquals(MONGO_ROW_INFOS[0]['row_id'], e2q.row2id(self.db, 'Rv1180'))
        for f in ROW_INFO_FIELDS:
            self.assertEquals(MONGO_ROW_INFOS[0][f], e2q.row2id(self.db, 'Rv1180', return_field=f))

    def test_row2id_by_row_id(self):
        self.assertEquals(MONGO_ROW_INFOS[0]['row_id'], e2q.row2id(self.db, 1179))
        for f in ROW_INFO_FIELDS:
            self.assertEquals(MONGO_ROW_INFOS[0][f], e2q.row2id(self.db, 1179, return_field=f))

    def test_row2id_by_egrin2_row_name(self):
        self.assertEquals(MONGO_ROW_INFOS[1]['row_id'], e2q.row2id(self.db, 'e2rname2'))
        for f in ROW_INFO_FIELDS:
            self.assertEquals(MONGO_ROW_INFOS[1][f], e2q.row2id(self.db, 'e2rname2', return_field=f))

    def test_row2id_by_gi(self):
        self.assertEquals(MONGO_ROW_INFOS[1]['row_id'], e2q.row2id(self.db, 456.0))
        for f in ROW_INFO_FIELDS:
            self.assertEquals(MONGO_ROW_INFOS[1][f], e2q.row2id(self.db, 456.0, return_field=f))

    def test_row2id_by_accession(self):
        self.assertEquals(MONGO_ROW_INFOS[0]['row_id'], e2q.row2id(self.db, 'NP_218441.1'))
        for f in ROW_INFO_FIELDS:
            self.assertEquals(MONGO_ROW_INFOS[0][f], e2q.row2id(self.db, 'NP_218441.1', return_field=f))

    def test_row2id_by_sysname(self):
        self.assertEquals(MONGO_ROW_INFOS[1]['row_id'], e2q.row2id(self.db, 'sys2'))
        for f in ROW_INFO_FIELDS:
            self.assertEquals(MONGO_ROW_INFOS[1][f], e2q.row2id(self.db, 'sys2', return_field=f))

    def test_row2id_by_sysname_all(self):
        self.assertEquals(MONGO_ROW_INFOS[1], e2q.row2id(self.db, 'sys2', return_field='all'))

    def test_row2id_no_match(self):
        self.assertIsNone(e2q.row2id(self.db, 'nevermatch'))

    def test_row2id_multi_match(self):
        self.assertIsNone(e2q.row2id(self.db_ambiguous, 'multimatch'))


if __name__ == '__main__':
    suite = [unittest.TestLoader().loadTestsFromTestCase(QueryTest)]

    if len(sys.argv) > 1 and sys.argv[1] == 'xml':
      xmlrunner.XMLTestRunner(output='test-reports').run(unittest.TestSuite(suite))
    else:
      unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suite))
