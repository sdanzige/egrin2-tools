#!/tools/bin/python
""" fimo.py
Author:  Micheleen M. Harris, David J Reiss
Description:  FIMO step of the EGRIN2 pipeline.  This program makes a script which can be submitted to 
an SGE scheduler on a cluster.

This script assumes an ensemble run under a directory structure that 
is as follows:

<dir>
  |-- <prefix>001
             |-- cmonkey_run.db
             |-- ...
  |-- <prefix>002
  |-- ...
  |-- <this is where shell scripts will be run with qsub>

Instructions:  Run resulting script (<name you choose>.sh) under <dir> as shown above.
Note:  if you are using c-shell make sure to use the --csh flag when running this program.

Example:

python fimo.py --genome 'cache/Escherichia_coli_K12_NC_*' --user mharris 
                --qsub_script fimo_batch_script.sh --csh --organism eco

Output will be in subdirectory to input directory (<prefix>001/fimo_outs/ for example will have all fimo 
files associated with the meme files).
"""

import optparse
import sys
import os
import glob

#  TODO:
#	-Instead of creating a fimo_script.sh for every run with simple multiple calls to fimo
#		make it such that this is more parallel (perhaps a fimo script for each meme file)
#	-Fix shell header to bash with an option like the '-f' in the csh shell header (maybe -profile?)
#	-Make the iteration through all MEME files to check e-value formats more efficient

#  Fimo command
FIMO_TEMPLATE = """fimo --max-stored-scores 9999999 --max-seq-length 1e8 --text --verbosity 2 %s %s | bzip2 -c > %s.bz2"""

SHELL_HEADER = """#!/bin/bash"""

# Templates for Bourne Shell
QSUB_TEMPLATE_HEADER = """#!/bin/bash

export LD_LIBRARY_PATH=/tools/lib:/tools/R-3.0.3/lib64/R/lib
export PATH=/tools/bin:${PATH}
export BATCHNUM=`printf "%03d" $SGE_TASK_ID`
"""

QSUB_TEMPLATE = """#$ -S /bin/bash
#$ -m be
#$ -q baliga
#$ -P Bal_%s
#$ -M %s@systemsbiology.org
#$ -t 1-%s
#$ -cwd
#$ -pe serial %s
#$ -l mem_free=2G

%s
"""


# Templates for csh

SHELL_HEADER_CSH = """#!/bin/csh -f"""

QSUB_TEMPLATE_HEADER_CSH = """#!/bin/csh -f

setenv LD_LIBRARY_PATH /tools/lib:/tools/R-3.0.3/lib64/R/lib
setenv PATH /tools/bin:${PATH}
set BATCHNUM="`printf '%03d' ${SGE_TASK_ID}`"
"""

QSUB_TEMPLATE_CSH = """#$ -S /bin/csh
#$ -m be
#$ -q baliga
#$ -P Bal_%s
#$ -M %s@systemsbiology.org
#$ -t 1-%s
#$ -cwd
#$ -pe serial %s
#$ -l mem_free=2G

%s
"""

def fix_meme_files(meme_files):
    for memef in meme_files:
    	fix_meme_file(memef)

def fix_meme_file(meme_files):
    #  Read memefile line by line and output, replacing strange e-value formats (e.g. "E= 10.0e+003" to "E= 1.0e+004")
    IN = open(memef,'rb')
    OUT = open(memef+'_fimo', 'wb')
    for line in IN:
      if 'letter-probability matrix' in line: # Note: fimo uses this matrix for input
        linespl = line.split()
        evalue = linespl[9].split('e')
        p1 = float(evalue[0]) # first part of evalue, want format to be 1.0 instead of 10.0 for e.g.
        if p1 >= 10.0: # this is something we need to change!
          p1 /= 10. # shift decimal
          p1 = round(p1,1) # round to 1 decimal place
          p2 = evalue[1] # second part of evalue, will have a + or - at beginning
          newevalue = ''
          if '+' in p2:
            p2 = p2.replace('+','')
            if p2 == '000':
              p2 = 0
              newevalue = "%se+%03d" % (str(p1),p2)
            else:
              p2 = int(p2.lstrip("0")) + 1 # now an int
              newevalue = "%se+%03d" % (str(p1),p2)
          else:
            p2 = p2.replace('-','')
            if p2 == '000':
              p2 = 0
              newevalue = "%se+%03d" % (str(p1),p2)
            else:
              p2 = int(p2.lstrip("0")) - 1 # now an int
              newevalue = "%se-%03d" % (str(p1),p2)
          linespl[9] = newevalue
          OUT.write(' '.join(linespl)+'\n')
      else:
        OUT.write(line)
    IN.close()
    OUT.close()
    os.rename((memef+'_fimo'),memef)

def main():
    #  Collect & check args
    op = optparse.OptionParser()
    op.add_option('-g', '--genome', help='The genome sequence file glob (i.e., cache/<organism name>_NC_*')
    op.add_option('-o', '--organism', help='KEGG name for organism (e.g. eco, hal')
    op.add_option('-u', '--user', help='User name on cluster')
    #op.add_option('-i', '--base_dir', default='.', help='Cmonkey-python base directory.')
    #op.add_option('-t', '--target_dir', default='.', help='The output directory name')
    op.add_option('-q', '--qsub_script', default='qsub_fimo.sh', help='The script name for running fimo on cmonkey results')
    ##op.add_option('-n', '--num_cores', default=1, help='Number of cores to use on cluster')
    op.add_option('-s', '--csh', help='If c-shell indicate with this flag', action='store_true')
    op.add_option('-f', '--fix', default=False, help='Fix meme files', action='store_true')
    opt, args = op.parse_args()

    if not opt.genome:
        op.error('need --genome option.  Use -h for help.')
    #if not opt.target_dir:
    #    op.error('need --target_dir option.  Use -h for help.')
    #if not opt.base_dir:
    #    op.error('need --base_dir option.  Use -h for help.')
    ##if not opt.num_cores:
    ##    op.error('need --num_cores option.  Use -h for help.')
    if not opt.qsub_script:
        op.error('need --qsub_script option.  Use -h for help.')
    if not opt.organism:
        op.error('need --organism option.  Use -h for help.')
    if not opt.user:
        op.error('need --user option.  Use -h for help.')

    if opt.csh:
        header = QSUB_TEMPLATE_HEADER_CSH
        template = QSUB_TEMPLATE_CSH
        shellheader = SHELL_HEADER_CSH
    else:
        header = QSUB_TEMPLATE_HEADER
        template = QSUB_TEMPLATE
        shellheader = SHELL_HEADER

    # Fix genome seqs file(s) for fimo (to upper and add header for fasta format), ouput to new file, 
    # put in cache dir (might be better way)
    seqsfiles = glob.glob(opt.genome)
    seqsfile_out = os.path.join(os.path.dirname(seqsfiles[0]), opt.organism)+'_genome.fst'
    out = open(seqsfile_out, 'wb')
    for fname in seqsfiles:
        seqsfile_in = open(fname, 'rb')
        lines = seqsfile_in.readlines()
        genomeseq = lines[0].upper() # to upper may not be necessary

        out.write(">"+fname[fname.find('_NC_')+1:]+'\n') ## just use chromosome NCBI code in fasta header - is this robust enough?
        out.write(genomeseq)
    out.close()

    #  Create a dict of run output dirs with array of meme file names
    org_out_dirs = glob.glob("%s-out-*" % opt.organism)
    ##out_dir_dict = {}

    for org_dir in sorted(org_out_dirs):
        print org_dir
        #  Find MEME files
        meme_files = sorted(glob.glob(os.path.join(org_dir, "meme-out-*")))
        if opt.fix:
            fix_meme_files(meme_files) # Fixes e-value formats  - TODO: make more efficient
        ##out_dir_dict[org_dir] = meme_files

        #  We will make a subscripts for each run directory to call fimo on all meme files within that directory
        ##sub_scripts = {}
        ##for org_dir in org_out_dirs:
        ##meme_files = out_dir_dict[org_dir]

        try:
            os.mkdir(os.path.join(org_dir, "fimo-outs")) ## location of output files
        except:
            None

        #  We will make a subscript for each run directory to call fimo on all meme files within that directory
        fimo_cmd = ""
        for meme in meme_files:
            num = os.path.basename(meme).split('-')[3] # Get the bicluster number
            #num = num[1:] # remove leading 0
            if os.path.isfile( os.path.join(org_dir, "fimo-outs/fimo-out-%s.bz2" % num) ):
                print 'SKIPPING:', os.path.join(org_dir, "fimo-outs/fimo-out-%s.bz2" % num)
                fimo_cmd += '\n' + 'echo SKIPPING, already exists "%s"' % (meme) + '\n'
            else:
                fimo_cmd += '\n' + 'echo "%s"' % (meme) + '\n'
                fimo_cmd += '\n' + FIMO_TEMPLATE % (meme, seqsfile_out, 
                                                    os.path.join(org_dir, "fimo-outs/fimo-out-%s" % num)) + '\n'

        ##sub_scripts[org_dir] = fimo_cmd

    ##for org_dir in org_out_dirs:
        outfile_name = os.path.join(org_dir, 'fimo_script.sh')
        with open(outfile_name, 'w') as outfile:
            #subscript_template = shellheader + '\n' + fimo_cmd ##sub_scripts[org_dir]
            outfile.write(shellheader + '\n')
            outfile.write(fimo_cmd) ##sub_scripts[org_dir])
            #rendered = Template(subscript_template).render()
            #outfile.write(rendered)
            #st = os.stat(outfile)
            #os.chmod(subscript, st.st_mode | stat.S_IEXEC)
        outfile.close()
        #st = os.stat(outfile)
        #os.chmod(subscript, st.st_mode | stat.S_IEXEC)
        os.chmod(outfile_name,0744)

    #  Create master script
    with open(opt.qsub_script, 'w') as outfile:
        if opt.user is not None:
            login = opt.user
        else:
            os.getlogin()

        ##num_runs = len(org_out_dirs)
	max_run = max( [int(i.split('-')[2]) for i in org_out_dirs] )
        subscript = "%s-out-${BATCHNUM}/fimo_script.sh >& %s-out-${BATCHNUM}/fimo_script.sh.out" % (opt.organism, \
                                                                                                    opt.organism)
        num_cores = 1 ## dont need more
        outfile.write(header + '\n')
        outfile.write(template % (login, 
            login,
            ##num_runs,
	    max_run,
            num_cores, 
            subscript))

    outfile.close()

if __name__ == '__main__':
    main()
    














