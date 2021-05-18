"""
File:		find_amrs_in_sample.py
Aythor:		Somayeh Kafaie
Date:		March 2021
Purpose:	To find all AMRs available in a metagenome sample,
	extract their neighborhood sequences and annotate them.

To run:
	python find_amrs_in_sample.py --db <metagenome file path>
    --seq <fasta file containing all AMR sequences>
Note: it reads 3 parameetrs from params.py:
	- params.PROKKA_COMMAND_PREFIX
	- params.use_RGI
	- params.RGI_include_loose
"""
#python /media/Data/PostDoc/Dalhousie/Work/Test1/codes/AMR_context/find_amrs_in_sample.py
#--db /media/Data/PostDoc/Dalhousie/Work/Test2/Experiments/1_1_1_limit/metagenome.fasta
#--seq /media/Data/PostDoc/Dalhousie/Work/Test2/nucleotide_fasta_protein_homolog_model_without_efflux_without_space.fasta
################################################################################

import sys
import os
import argparse
import csv
import collections
import datetime
import logging
from Bio import SeqIO
from gfapy.sequence import rc
import params
from utils import create_fasta_file, annotate_sequence, split_up_down_info,\
            similar_seq_annotation_already_exist, restricted_amr_name_from_modified_name,\
            amr_name_from_comment

def write_annotations_into_file(annotation_file, amr_name, up_info_desc_list,
                            amr_info_desc_list, down_info_desc_list):
    """
    """
    with open(annotation_file, 'a') as fd:
        writer = csv.writer(fd)
        for up_info_desc in up_info_desc_list:
            seq_description = up_info_desc[1]
            for gene_info in up_info_desc[0]:
                writer.writerow([amr_name, 'up_stream', seq_description, gene_info['seq_value'],
                len(gene_info['seq_value']), gene_info['gene'], gene_info['prokka_gene_name'],
                gene_info['product'], gene_info['length'], gene_info['start_pos'],
                gene_info['end_pos'], gene_info['RGI_prediction_type'], gene_info['family']])
        for amr_info_desc in amr_info_desc_list:
            seq_description = amr_info_desc[1]
            gene_info = amr_info_desc[0]
            writer.writerow([amr_name, 'target_amr', seq_description, gene_info['seq_value'],
            len(gene_info['seq_value']), gene_info['gene'], gene_info['prokka_gene_name'],
            gene_info['product'], gene_info['length'], gene_info['start_pos'],
            gene_info['end_pos'], gene_info['RGI_prediction_type'], gene_info['family']])
        for down_info_desc in down_info_desc_list:
            seq_description = down_info_desc[1]
            for gene_info in down_info_desc[0]:
                writer.writerow([amr_name, 'down_stream', seq_description, gene_info['seq_value'],
                len(gene_info['seq_value']), gene_info['gene'], gene_info['prokka_gene_name'],
                gene_info['product'], gene_info['length'], gene_info['start_pos'],
                gene_info['end_pos'], gene_info['RGI_prediction_type'], gene_info['family']])

def annotate_neighborhood_sequences(ref_ng_info_list):
    """
    """
    error_file ="not_found_annotation_amrs_in_ref.txt"
    error_writer = open(error_file, 'w')
    annotate_dir = 'ref_annotations/'
    if not os.path.exists(annotate_dir):
        os.makedirs(annotate_dir)
    annotation_file = 'ref_neighborhood_annotations.csv'
    with open(annotation_file,  'a') as fd:
        writer = csv.writer(fd)
        writer.writerow(['target_amr', 'gene_location', 'seq_name', 'seq_value',
            'seq_length', 'gene', 'prokka_gene_name', 'product', 'length',
            'start_pos', 'end_pos', 'RGI_prediction_type', 'family'])
    for amr_info_list in ref_ng_info_list:
        amr_name = amr_info_list[0]
        ref_up_info_list = []
        ref_amr_info_list = []
        ref_down_info_list = []
        up_description_list = []
        amr_description_list = []
        down_description_list = []
        for index, amr_info in enumerate(amr_info_list[1]):
            contig_name = amr_info['contig']
            seq = amr_info['seq']
            seq_description = 'ref_'+amr_name+'_'+contig_name.replace(' ','_').replace('.','').replace(',','')
            amr_name1 = restricted_amr_name_from_modified_name(amr_name)
            annotation_prefix = 'ref_'+ amr_name1 +'__'+str(index)
            seq_info = annotate_sequence(seq+"\n", annotation_prefix, annotate_dir,
                    params.PROKKA_COMMAND_PREFIX, params.use_RGI, params.RGI_include_loose)
            found, ref_amr_info , ref_up_info, ref_down_info, seq_info = split_up_down_info(seq, seq_info)
            if found:
                if ref_up_info and not similar_seq_annotation_already_exist(ref_up_info, ref_up_info_list):
                    ref_up_info_list.append(ref_up_info)
                    up_description_list.append(seq_description)
                if ref_down_info and not similar_seq_annotation_already_exist(ref_down_info, ref_down_info_list):
                    ref_down_info_list.append(ref_down_info)
                    down_description_list.append(seq_description)
                ref_amr_info_list.append(ref_amr_info)
                amr_description_list.append(seq_description)
            else:
                logging.error("No target amr was found in the ref sequence")
                error_writer.write(amr_name+' annotation not found in ref_contig: '+contig_name+" seq_info: "+str(seq_info)+'\n')
        if ref_amr_info_list:
            write_annotations_into_file(annotation_file, amr_name, zip(ref_up_info_list, up_description_list),
                zip(ref_amr_info_list, amr_description_list), zip(ref_down_info_list, down_description_list))
        else:
            error_writer.write(amr_name+' no annotation was found in reference.\n')
    logging.info("NOTE: The annotation of neighborhood sequences in reference genome(s) has\
        been stroed in " + annotation_file)
    error_writer.close()
    return annotation_file

def extract_amr_length(amr_sequences_file):
    """
    """
    amr_objects = []
    with open(amr_sequences_file) as fp:
        for line in fp:
            if line.startswith('>'):
                amr_comment = line[1:-1]
                continue
            amr_name = amr_name_from_comment(amr_comment)
            amr_object={'name':amr_name, 'length':len(line)-1, 'seq': line[:-1], 'title':amr_comment}
            amr_objects.append(amr_object)
    return amr_objects

def find_all_amrs_and_neighborhood(amr_sequences_file, genome_file, neighborhood_len = 1000, threshold = 95):
    """
    """
    blast_file_name = 'blast_out.csv'
    if not os.path.isfile(blast_file_name):
        # Find the length of each AMR sequence
        amr_objects = extract_amr_length(amr_sequences_file)
        #creat blast database from the (meta)genome file
        command = 'makeblastdb -in '+genome_file +' -parse_seqids -dbtype nucl'
        os.system(command)
        #Run Blastn
        # command = 'blastn -query '+amr_sequences_file+' -db '+genome_file+\
        #     ' -task blastn -outfmt 10 -evalue 0.5 -perc_identity '+str(threshold-1)+\
        #     ' -num_threads 4 > '+ blast_file_name
        command = 'blastn -query '+amr_sequences_file+' -db '+genome_file+\
            ' -outfmt 10 -evalue 0.5 -perc_identity '+str(threshold-1)+\
            ' -num_threads 4 > '+ blast_file_name
        os.system(command)

    AMR_dir = 'sequences/'
    ng_file = 'AMR_ref_neighborhood.fasta'
    if not os.path.exists(AMR_dir) or not os.path.isfile(ng_file):
        #Read the blast result
        amr_list = []
        amr = collections.namedtuple('amr', 'amr_name seq_name identity matched_length q_start q_end c_start c_end')
        with open(blast_file_name, 'r') as file1:
            myfile = csv.reader(file1)
            for row in myfile:
                myamr = amr(amr_name=row[0], seq_name=row[1], identity=row[2],
                    matched_length=row[3], q_start=row[6], q_end=row[7],
                    c_start=row[8], c_end=row[9])
                amr_list.append(myamr)
        #Find the list of detected AMRs
        amr_start_list = []
        amr_end_list = []
        record_name_list = []
        amr_name_list = []
        if not os.path.exists(AMR_dir):
            os.makedirs(AMR_dir)
        # find the start and end of AMR for all found cases above the threshold
        for record in amr_list:
            if int(float(record.identity))>=threshold:
                target_amr = next((amr_obj for amr_obj in amr_objects if amr_obj['title'].split(' ')[0] == record.amr_name), None)
                if target_amr and int(float(record.matched_length)/target_amr['length']*100)>=threshold:
                    if target_amr['name'] not in amr_name_list:
                        amr_file_name = restricted_amr_name_from_modified_name(target_amr['name'])
                        amr_file = create_fasta_file(target_amr['seq']+'\n', AMR_dir, '>'+target_amr['title']+'\n', amr_file_name)
                    amr_name_list.append(target_amr['name'])
                    amr_start_list.append(int(record.c_start))
                    amr_end_list.append(int(record.c_end))
                    record_name_list.append(record.seq_name)
                elif not target_amr:
                    print("ERROR: couldn't find the length of AMR: "+record.amr_name)
                    import pdb; pdb.set_trace()
                    sys.exit()
        # extract neighborhood sequence(s)
        ng_lists = []
        amr_list = []
        with open(ng_file, 'w') as myfile:
            seq_list = []
            contig_name_list = []
            for i, amr_start in enumerate(amr_start_list):
                amr_end = amr_end_list[i]
                record_name = record_name_list[i]
                seq = ''
                reverse_complement = False
                # extract sequence from both sides
                if amr_start > amr_end:
                    amr_start, amr_end = amr_end, amr_start
                    reverse_complement = True
                for record in SeqIO.parse(open(genome_file,'r'),'fasta'):
                    #if record.id == record_name:
                    if record_name == record.id:
                        amr_start = amr_start -1
                        if amr_start-neighborhood_len >= 0:
                            seq = str(record.seq[amr_start-neighborhood_len:amr_start]).upper()+str(record.seq[amr_start:amr_end]).lower()
                            amr_start = neighborhood_len
                        else:
                            seq = str(record.seq[:amr_start]).upper()+str(record.seq[amr_start:amr_end]).lower()
                        if (amr_end-1+neighborhood_len)<=len(record):
                            seq+=str(record.seq[amr_end:amr_end+neighborhood_len])
                        else:
                            seq+=str(record.seq[amr_end:])
                        if reverse_complement:
                            seq = rc(seq)
                        ng_item ={'contig':record.description, 'seq':seq}
                        if amr_name_list[i] not in amr_list:
                            amr_list.append(amr_name_list[i])
                            ng_lists.append([ng_item])
                        else:
                            amr_index = amr_list.index(amr_name_list[i])
                            ng_lists[amr_index].append(ng_item)
                        myfile.write('>'+amr_name_list[i]+'::'+record.description+'\n')
                        myfile.write(seq+'\n')
                        break
    else:
        amr_list = []
        ng_lists = []
        with open(ng_file, 'r') as myfile:
            for line in myfile:
                if line.startswith('>'):
                    items = line[1:-1].split('::')
                    amr_name = items[0]
                    contig_name = items[1]
                else:
                    ng_item ={'contig':contig_name, 'seq':line[:-1]}
                    if amr_name not in amr_list:
                        amr_list.append(amr_name)
                        ng_lists.append([ng_item])
                    else:
                        amr_index = amr_list.index(amr_name)
                        ng_lists[amr_index].append(ng_item)

    return zip(amr_list, ng_lists)

def find_annotate_amrs_in_ref(seq, db):
	"""
	"""
	if seq and db:
		ref_ng_info = find_all_amrs_and_neighborhood(seq, db)
		annotation_file = annotate_neighborhood_sequences(ref_ng_info)
		return 1
	else:
		return -1

def main(args):
	"""
	"""
	if find_annotate_amrs_in_ref(arg.seq, args.db)==-1:
		print('please enter the path for the sample file and amr sequences file')
		import pdb; pdb.set_trace()
		sys.exit()

if __name__=="__main__":
    text = 'This code is used to find all AMRs available in a metagenome sample'
    parser = argparse.ArgumentParser(description=text)
    parser.add_argument('--db', type=str, default='',
        help='the path of the file containing the (meta)genome sample')
    parser.add_argument('--seq', type=str, default = '',
        help = 'the path of the fasta file containing all AMR sequences')
    args = parser.parse_args()
    main(args)