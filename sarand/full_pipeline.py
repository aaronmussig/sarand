"""
File:		full_pipeline.py
Author:		Somayeh Kafaie
Date:		September 2020


Purpose:	To extract the neighborhood of an AMR gene from an assembly graph,
            annotate it and compare with the reference genome(s)

To run:
    python full_pipeline.py

NOTE: all parameters can be set in params.py
NOTE: if use_RGI = TRUE, make sure either RGI has been installed system-wide or
    you already are in the environment RGI installed in!
"""
import copy
import csv
import os
import shutil
import sys
from functools import partial
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Dict, List, Any

from sarand.annotation_visualization import visualize_annotation
from sarand.config import AMR_DIR_NAME, AMR_SEQ_DIR, AMR_ALIGN_DIR, AMR_OVERLAP_FILE, SEQ_DIR_NAME, SEQ_NAME_PREFIX, \
    ANNOTATION_DIR
from sarand.external.graph_aligner import GraphAligner, GraphAlignerParams
from sarand.extract_neighborhood import neighborhood_sequence_extraction
from sarand.model.fasta_seq import FastaSeq
from sarand.util.file import try_dump_to_disk
from sarand.util.logger import LOG
from sarand.utils import (
    retrieve_AMR,
    create_fasta_file,
    split_up_down_info,
    seqs_annotation_are_identical,
    similar_seq_annotation_already_exist,
    amr_name_from_comment,
    extract_name_from_file_name,
    restricted_amr_name_from_modified_name,
    delete_lines_started_with,
    read_path_info_from_align_file_with_multiple_amrs,
    annotate_sequence,
    extract_amr_sequences,
)


def write_info_in_annotation_file(
        annotation_writer, visual_annotation_writer, gene_info, no_RGI, found, len_seq=None
):
    """
    To write annotation details into files
    Parameters:
        annotation_writer:	annotation file containing all annotations
        visual_annotation_writer: annotation file containing unique annotations
        seq_description: a small description of the sequence used for naming
        seq: the extracted dna sequence that has been annotated
        gene_info: annotation info
        contig_name: the name of contig matching this extracted sequence (if there is any contig)
        no_RGI: if True, RGI has not been used to annotate AMRs
        found: if True, the annotation info has already found in other annotated sequences
    """
    seq = gene_info["seq_value"]
    seq_description = gene_info["seq_name"]
    if len_seq is None:
        len_seq = len(seq)
    if not no_RGI:
        annotation_writer.writerow(
            [
                seq_description,
                seq,
                len_seq,
                gene_info["gene"],
                # gene_info["prokka_gene_name"],
                gene_info["product"],
                gene_info["length"],
                gene_info["start_pos"],
                gene_info["end_pos"],
                gene_info["RGI_prediction_type"],
                gene_info["coverage"],
                gene_info["family"],
                gene_info["target_amr"],
            ]
        )
        if not found:
            visual_annotation_writer.writerow(
                [
                    seq_description,
                    seq,
                    len_seq,
                    gene_info["gene"],
                    # gene_info["prokka_gene_name"],
                    gene_info["product"],
                    gene_info["length"],
                    gene_info["start_pos"],
                    gene_info["end_pos"],
                    gene_info["RGI_prediction_type"],
                    gene_info["coverage"],
                    gene_info["family"],
                    gene_info["target_amr"],
                ]
            )
    else:
        annotation_writer.writerow(
            [
                seq_description,
                seq,
                len_seq,
                gene_info["gene"],
                gene_info["product"],
                gene_info["length"],
                gene_info["start_pos"],
                gene_info["end_pos"],
                gene_info["coverage"],
                gene_info["target_amr"],
            ]
        )
        if not found:
            visual_annotation_writer.writerow(
                [
                    seq_description,
                    seq,
                    len_seq,
                    gene_info["gene"],
                    gene_info["product"],
                    gene_info["length"],
                    gene_info["start_pos"],
                    gene_info["end_pos"],
                    gene_info["coverage"],
                    gene_info["target_amr"],
                ]
            )


def seq_annotation_already_exist(seq_info_list, all_seq_info_lists, out_dir):
    """
    To check if annotations found for the new sequence have already exists in the
    list of annotations extracted from other sequences.
    Parameters:
        seq_info_list: list of annotations of the new sequence
        all_seq_info_lists: list of annotations of the other sequences annotated so far
    Return:
        True if seq_info_list is identical to another list in all_seq_info_lists in
        terms of 'gene', 'length','start_pos' and 'end_pos' for all thei items
    """
    found = False
    for seq_list in all_seq_info_lists:
        if seqs_annotation_are_identical(seq_info_list, seq_list, out_dir, 100):
            found = True
            break

    return found


def read_path_info_file(path_info_file):
    """
    To read the csv file containing the list of nodes and their coverage representing
    in an extracted sequence
    Parameter:
        path_info_file: the csv file
    Return:
        stored info in a list
    """
    seq_info_list = []
    seq_info = []
    with open(path_info_file, "r") as myfile:
        myreader = csv.DictReader(myfile)
        old_seq = ""
        for row in myreader:
            # @Somayeh: hacky fix for whatever is causing the path info files
            # to contain the same data duplicated
            # sequence,node,coverage,start,end
            # 1,127,12.603822917195512,0,999
            # 1,127,12.603822917195512,1000,1731
            # 1,127,12.603822917195512,1732,2731
            # sequence,node,coverage,start,end
            # 1,127,12.603822917195512,0,999
            # 1,127,12.603822917195512,1000,1731
            # 1,127,12.603822917195512,1732,2731
            # sequence,node,coverage,start,end
            # 1,127,12.603822917195512,0,999
            # 1,127,12.603822917195512,1000,1731
            # 1,127,12.603822917195512,1732,2731
            if row["coverage"] == "coverage":
                continue
            node_info = {
                "node": row["node"],
                "coverage": float(row["coverage"]),
                "start": int(row["start"]),
                "end": int(row["end"]),
            }
            cur_seq = row["sequence"]
            if cur_seq != old_seq:
                if seq_info:
                    seq_info_list.append(seq_info)
                seq_info = []
                old_seq = cur_seq
            seq_info.append(node_info)
        seq_info_list.append(seq_info)
    return seq_info_list


def find_gene_coverage(seq_info_list, path_info):
    """
    Calculate the coverage of genes available in a sequence based on the coverage
    of the nodes representing them
    Parameter:
        seq_info_list: the list of genes (and their info) annotated in a sequence
        path_info:	the list of nodes (and their info) representing the sequence
    Return:
        the list of calculated gene-coverages
    """
    coverage_list = []
    for seq_info in seq_info_list:
        sum_coverage = 0
        # minus 1 because I guess in what prokka returns the sequence starts from position 1
        start, end = seq_info["start_pos"] - 1, seq_info["end_pos"] - 1
        if start > end:
            start, end = end, start
        found = False
        for j, node_info in enumerate(path_info):
            if node_info["start"] <= start and node_info["end"] >= start:
                found = True
                # the annotated gene is represented by a single node
                if node_info["end"] >= end:
                    sum_coverage = (end - start + 1) * node_info["coverage"]
                else:
                    # calculate the length of node representing the gene
                    sum_coverage = (node_info["end"] - start + 1) * node_info[
                        "coverage"
                    ]
                    n_index = j + 1
                    assert n_index < len(
                        path_info
                    ), "wrong index calculated for path_info!!"
                    while (
                            n_index < len(path_info) and path_info[n_index]["start"] <= end
                    ):
                        if path_info[n_index]["end"] >= end:
                            sum_coverage += (
                                                    end - path_info[n_index]["start"] + 1
                                            ) * path_info[n_index]["coverage"]
                            break
                        else:
                            sum_coverage += (
                                                    path_info[n_index]["end"]
                                                    - path_info[n_index]["start"]
                                                    + 1
                                            ) * path_info[n_index]["coverage"]
                        n_index += 1
                coverage_list.append(sum_coverage / (end - start + 1))
                break
        if not found:
            LOG.error("ERROR: no nodes were found for this gene!!!")
            import pdb

            pdb.set_trace()
            sys.exit(1)
    return coverage_list


def find_target_amr_in_seqvalue_and_return_coverage(seq_info):
    """
    To find the target AMR in a sequence and its covearge:
    We first look at the extracted sequence as the part of the sequence in lower-case
    represents the AMR; then, we look at the list of annotated genes and find the
    gene that has the most overlap with the lower-case area and finally find its coverage
    Parameters:
        seq_info: the details of an extracted sequences and its annotation
    Return:
        the coverage of the AMR, its index in seq_info and False if we can find a
        gene in the lower-case area of the sequence; otherwise it returns True
    """
    error = True
    amr_coverage = 0
    # find the indeces of lower case string (amr sequence) in the extracted sequence
    sequence = seq_info[0]["seq_value"]
    amr_start = -1
    amr_end = -1
    index = 0
    while index < len(sequence):
        if sequence[index].islower() and amr_start == -1:
            amr_start = index
        elif sequence[index].isupper() and amr_start > -1:
            amr_end = index - 1
            break
        index += 1
    # find the gene has the most overlap with the found range
    # we look at all found genes that their overlap with the sequence is more than initial value of most_overlap and chose the one with max
    most_overlap = 50
    amr_index = -1
    for i, gene_info in enumerate(seq_info):
        start, end = min(gene_info["start_pos"], gene_info["end_pos"]), max(
            gene_info["start_pos"], gene_info["end_pos"]
        )
        if end < amr_start or start > amr_end:
            continue
        else:
            # added by 1 because in string indecesstarts from 0
            diff = max((amr_start + 1 - start), 0) + max((end - (amr_end + 1)), 0)
            if ((1 - (float(diff) / (end - start))) * 100) > most_overlap:
                most_overlap = (1 - (float(diff) / (end - start))) * 100
                amr_coverage = gene_info["coverage"]
                amr_index = i
                error = False
    return amr_coverage, amr_index, error


def check_coverage_consistency_remove_rest_seq(
        seq_info_list_input, coverage_thr, amr_name, annotate_dir
):
    """
    To compare the coverage of each gene in the neighborhood with that of the AMR
    and remove the gene (and any gene before that in case of upstream and any gene
    after that in case of downstream) if the difference between this gene's coverage
    and ame coverage is more than covearge_thr
    Parameters:
        seq_info_list_input: the list of all sequences and their info including annotations
        coverage_thr:	the threshold used to compare the gene covearge and amr covearge
        amr_name:	the name of target AMR
        annotate_dir:	the directory in which annotation info are stored
    Return:
    """
    seq_info_list = copy.deepcopy(seq_info_list_input)
    # extract amr info
    amr_coverages = []
    amr_indeces = []
    for seq_info in seq_info_list:
        found_amr = False
        for gene_counter, gene_info in enumerate(seq_info):
            if gene_info["coverage"] is None:
                LOG.info("Coverage information are not available for " + amr_name)
                return "", 0
            coverage = round(gene_info["coverage"], 2)
            if gene_info["target_amr"] == "yes":
                amr_coverages.append(coverage)
                amr_indeces.append(gene_counter)
                found_amr = True
                break
        if not found_amr:
            (
                amr_coverage,
                amr_index,
                error,
            ) = find_target_amr_in_seqvalue_and_return_coverage(seq_info)
            if error:
                LOG.error(
                    "No target amr was found for "
                    + str(seq_info)
                    + " regarding "
                    + amr_name
                )
                import pdb

                pdb.set_trace()
                sys.exit(1)
            else:
                amr_coverages.append(amr_coverage)
                amr_indeces.append(amr_index)
    if len(amr_coverages) != len(seq_info_list):
        LOG.error(
            "Inconsistency between the number of sequences and found amr-coverages!"
        )
        import pdb

        pdb.set_trace()
    # check coverage consistency by comparing its coverage with AMR coverage
    # and remove genes with inconsistent coverage and whatever comes before them if upstream OR after them if downstream
    remained_seqs = []
    for i, seq_info in enumerate(seq_info_list):
        # find the genes need to be removed
        to_be_removed_genes = []
        for j, gene_info in enumerate(seq_info):
            if abs(gene_info["coverage"] - amr_coverages[i]) > coverage_thr:
                if j < amr_indeces[i]:
                    for k in range(j + 1):
                        if k not in to_be_removed_genes:
                            to_be_removed_genes.append(k)
                elif j > amr_indeces[i]:
                    for k in range(j, len(seq_info)):
                        if k not in to_be_removed_genes:
                            to_be_removed_genes.append(k)
                    break
        for j in reversed(range(len(seq_info))):
            if j in to_be_removed_genes:
                del seq_info[j]
        # check if the remained sequence already exists in the seq_info_list
        if seq_info and not similar_seq_annotation_already_exist(
                seq_info, remained_seqs, annotate_dir
        ):
            remained_seqs.append(seq_info)

    # Initialize coverage file
    coverage_annotation = os.path.join(
        annotate_dir,
        "coverage_annotation_" + str(coverage_thr) + "_" + amr_name + ".csv",
    )
    with open(coverage_annotation, "w") as fd:
        writer = csv.writer(fd)
        writer.writerow(
            [
                "seq_name",
                "seq_value",
                "seq_length",
                "gene",
                "coverage",
                "length",
                "start_pos",
                "end_pos",
                "target_amr",
            ]
        )
        # write extracted sequences with consistent coverage
        for seq_info in remained_seqs:
            for gene_info in seq_info:
                writer.writerow(
                    [
                        gene_info["seq_name"],
                        gene_info["seq_value"],
                        len(gene_info["seq_value"]),
                        gene_info["gene"],
                        gene_info["coverage"],
                        gene_info["length"],
                        gene_info["start_pos"],
                        gene_info["end_pos"],
                        gene_info["target_amr"],
                    ]
                )

    return coverage_annotation, len(remained_seqs)


def extract_seq_annotation(annotate_dir, no_RGI, RGI_include_loose, seq_pair):
    """
    The function used in parallel anntation to call the function for annotating a sequence
    Parameters:
        annotate_dir: the directory to store annotation output
        no_RGI: if True we want to call RGI for annotating AMRs
        RGI_include_loose: if True loose mode is used
        seq_pair: the index and the value of a sequence to be annotated
    Return:
        the list of annotated genes
    """
    counter, ext_seq = seq_pair
    seq_description = "extracted" + str(counter)
    seq_info_list = annotate_sequence(
        ext_seq,
        seq_description,
        annotate_dir,
        no_RGI,
        RGI_include_loose,
    )
    return seq_info_list


def extract_graph_seqs_annotation(
        amr_name,
        path_info_file,
        neighborhood_seq_file,
        annotate_dir,
        core_num,
        no_RGI,
        RGI_include_loose,
        annotation_writer,
        trimmed_annotation_writer,
        gene_file,
        error_file,
):
    """
    To annotate neighborhood sequences of AMR extracted from the graph in parallel
    Parameters:
        amr_name: the name of AMR
        path_info_file: the information of nodes representing the extracted sequence
        neighborhood_seq_file: the file containing extracted sequences
        annotate_dir: the directory to sore annotation results
        core_num: the number of core for parallel processing
        no_RGI: if True RGI is not used for AMR annotation
        RGI_include_loose: if True use loose mode in RGI
        annotation_writer: the file to store annotation results
        trimmed_annotation_writer: the file to store unique annotation results
        gene_file: the file to store gene nams in annotation
        error_file: the file to store errors
    Return:
        the list of annotated genes and their details
    """
    error_writer = open(error_file, "a")
    # Read path_info from the file
    path_info_list = []
    if path_info_file != -1:
        path_info_list = read_path_info_file(path_info_file)
    # find the list of all extracted sequences
    LOG.debug("Reading " + neighborhood_seq_file + " for " + amr_name)
    sequence_list = []
    counter = 1
    with open(neighborhood_seq_file, "r") as read_obj:
        for line in read_obj:
            if (
                    line.startswith(">")
                    or line.startswith("Path")
                    or line.startswith("The")
            ):
                continue
            sequence_list.append((counter, line))
            counter += 1

    # Parallel annotation
    """
    AM: Do not initialise a multiprocessing pool if only one thread is required.
    """
    if core_num == 1:
        seq_info_list = list()
        for x in sequence_list:
            seq_info_list.append(extract_seq_annotation(annotate_dir, no_RGI, RGI_include_loose, x))
    else:
        p_annotation = partial(
            extract_seq_annotation, annotate_dir, no_RGI, RGI_include_loose
        )
        with Pool(core_num) as p:
            seq_info_list = p.map(p_annotation, sequence_list)

    # Further processing of result of parallel annotation
    all_seq_info_list = []
    # if amr_name=='GES-4' or amr_name=='GES-21':
    # 	import pdb; pdb.set_trace()
    for i, seq_pair in enumerate(sequence_list):
        counter, line = seq_pair
        seq_description = "extracted" + str(counter)
        seq_info = seq_info_list[i]
        # extract amr from seq_info
        amr_found, amr_info, up_info, down_info, seq_info = split_up_down_info(
            line[:-1], seq_info
        )
        if not amr_found:
            LOG.error("ERROR: no target amr was found in the extracted sequence")
            error_writer.write(
                amr_name
                + " annotation not found! "
                + " seq_info: "
                + str(seq_info)
                + "\n"
            )
            continue
            # import pdb; pdb.set_trace()
        # calculate coverage for the genes available in the annotation
        coverage_list = []
        if path_info_list:
            coverage_list = find_gene_coverage(seq_info, path_info_list[counter - 1])
        # Check if this annotation has already been found
        found = seq_annotation_already_exist(seq_info, all_seq_info_list, annotate_dir)
        # If it's a novel sequence correct annotation (if applicable) for cases that RGI doesn't have a hit but Prokka has
        if not found:
            all_seq_info_list.append(seq_info)
        myLine1 = seq_description + ":\t"
        # write annotation onfo into the files
        for j, gene_info in enumerate(seq_info):
            coverage = coverage_list[j] if coverage_list else -1
            gene_info["coverage"] = coverage
            gene_info["seq_name"] = seq_description
            write_info_in_annotation_file(
                annotation_writer, trimmed_annotation_writer, gene_info, no_RGI, found
            )
            if gene_info["gene"] == "":
                myLine1 += "UNKNOWN---"
            else:
                myLine1 += gene_info["gene"] + "---"
        gene_file.write(myLine1[:-3] + "\n")
    if not all_seq_info_list:
        error_writer.write(amr_name + " no annotation was found in the graph.\n")
    error_writer.close()
    return all_seq_info_list


def neighborhood_annotation(
        amr_name,
        neighborhood_seq_file,
        path_info_file,
        seq_length,
        output_dir,
        no_RGI=False,
        RGI_include_loose=False,
        output_name="",
        core_num=4,
):
    """
    To annotate reference genomes (a piece extracted around the AMR gene) as well as
        extracted neighborhood sequences from assembly graph, summarize the results
        in a couple of formats and visualize them
    Parameters:
        amr_name:	the name of target AMR
        neighborhood_seq_file:	the address of the file containing all extracted
             neighborhood sequences from assembly graph
        seq_length:	the length of neighborhood sequence extracted from each side of
            the AMR sequence (downstream and up stream)
        output_dir:	the path for the output directory
        no_RGI:	RGI annotations not incorporated for AMR annotation
        RGI_include_loose: Whether to include loose annotaions in RGI
        output_name:the name used to distinguish different output files usually based on the name of AMR
    Return:
        the address of files stroing annotation information (annotation_detail_name,
            trimmed_annotation_info, gene_file_name, visual_annotation)
    """
    LOG.info("Annotating " + amr_name)
    # initializing required files and directories
    annotate_dir = os.path.join(
        output_dir,
        ANNOTATION_DIR,
        ANNOTATION_DIR + "_" + str(seq_length),
        "annotation" + output_name + "_" + str(seq_length),
    )
    if os.path.exists(annotate_dir):
        try:
            shutil.rmtree(annotate_dir)
        except OSError as e:
            LOG.error("Error: %s - %s." % (e.filename, e.strerror))
    os.makedirs(annotate_dir)
    error_file = os.path.join(
        output_dir,
        ANNOTATION_DIR,
        ANNOTATION_DIR + "_" + str(seq_length),
        "not_found_annotation_amrs_in_graph.txt",
    )
    annotation_detail_name = os.path.join(
        annotate_dir, "annotation_detail" + output_name + ".csv"
    )
    trimmed_annotation_info_name = os.path.join(
        annotate_dir, "trimmed_annotation_info" + output_name + ".csv"
    )
    annotation_detail = open(annotation_detail_name, mode="w", newline="")
    trimmed_annotation_info = open(trimmed_annotation_info_name, mode="w", newline="")
    annotation_writer = csv.writer(annotation_detail)
    trimmed_annotation_writer = csv.writer(trimmed_annotation_info)
    gene_info = {
        "seq_value": "seq_value",
        "gene": "gene",
        # "prokka_gene_name": "prokka_gene_name",
        "product": "product",
        "length": "length",
        "start_pos": "start_pos",
        "end_pos": "end_pos",
        "RGI_prediction_type": "RGI_prediction_type",
        "coverage": "coverage",
        "family": "family",
        "seq_name": "seq_name",
        "target_amr": "target_amr",
    }
    write_info_in_annotation_file(
        annotation_writer,
        trimmed_annotation_writer,
        gene_info,
        no_RGI,
        False,
        "seq_length",
    )
    gene_file_name = os.path.join(
        annotate_dir, "seq_comparison_genes" + output_name + ".txt"
    )
    gene_file = open(gene_file_name, "w")

    # annotate the sequences extraced from assembly graph
    all_seq_info_list = extract_graph_seqs_annotation(
        amr_name,
        path_info_file,
        neighborhood_seq_file,
        annotate_dir,
        core_num,
        no_RGI,
        RGI_include_loose,
        annotation_writer,
        trimmed_annotation_writer,
        gene_file,
        error_file,
    )
    LOG.debug(
        "The comparison of neighborhood sequences are available in "
        + annotation_detail_name
        + ", "
        + gene_file_name
    )
    annotation_detail.close()
    trimmed_annotation_info.close()
    gene_file.close()

    return all_seq_info_list, trimmed_annotation_info_name


def amr_path_overlap(found_amr_paths, new_paths, new_amr_len, overlap_percent=95):
    """
    To check if all paths found for the new AMR seq overlap significantly (greater/equal
     than/to overlap percent) with the already found paths for other AMRs
    Parameters:
         found_amr_paths:  	the paths already found for AMR genes
        new_paths: 			the paths found for the new AMR gene
        overlap_percent:	the threshold for overlap
    Return:
        False only if every paths in new_paths have overlap with at least one path in found_amr_paths
        True if we can find at least one path that is unique and not available in found_amr_paths
        Also, it returns the list of indeces from found_amr_paths that had overlap with a path in new_paths
    """
    id_list = []
    for new_path in new_paths:
        found = False
        for i, paths in enumerate(found_amr_paths):
            for path in paths:
                if (
                        path["nodes"] == new_path["nodes"]
                        and path["orientations"] == new_path["orientations"]
                ):
                    # for now we just check overlaps when they are in the same node(s)
                    diff_length = max(
                        path["start_pos"] - new_path["start_pos"], 0
                    ) + max(new_path["end_pos"] - path["end_pos"], 0)
                    percent = (1 - (float(diff_length) / (new_amr_len))) * 100
                    if percent >= overlap_percent:
                        found = True
                        if i not in id_list:
                            id_list.append(i)
                        break
            if found:
                break
    if len(id_list) == len(new_paths):
        return True, id_list
    return False, None


def are_there_amrs_in_graph(
        gfa_file: Path,
        output_dir: Path,
        threshold: float,
        amr_path: Path,
        ga_extra_args: GraphAlignerParams,
        keep_files: bool,
        threads: int,
        debug: bool
) -> Dict[str, List[Dict[str, Any]]]:
    """
    To call bandage+blast and check if the amr sequence can be found in the assembly graph
    Parameters:
        amr_file: the address of the query file
        amr_name: the name of the AMR sequence
        gfa_file: the address of the assembly graph
        output_dir: the address of the output directory
        threshold: the threshold for coverage and identity
    Return:
        a boolean value which is True if amr_file was found in gfa_file and the
        list of paths returned by bandage+blast in which the coverage and identiry
        are greater/equal than/to threshold
    """

    # Run GraphAligner
    ga_path = output_dir if keep_files else None
    ga = GraphAligner.run_for_sarand(
        gfa=gfa_file,
        reads=amr_path,
        threshold=threshold,
        ga_extra_args=ga_extra_args,
        out_dir=ga_path,
        threads=threads
    )

    paths_info_list = read_path_info_from_align_file_with_multiple_amrs(
        output_name=output_dir,
        ga=ga.results,
        threshold=threshold,
        debug=debug,
    )

    return paths_info_list


def find_all_amr_in_graph(
        gfa_file: Path,
        output_dir: str,
        amr_sequences_file: Path,
        amr_threshold: float,
        core_num: int,
        ga_extra_args: GraphAlignerParams,
        keep_files: bool,
        debug: bool
):
    """
    To go over a list of AMR sequences (amr_sequences_file) and run bandage+blast
    to check if any of them exists in the assembly graph (gfa_file)
    Parameters:
        gfa_file: the address of the assembly graph
        output_dir: the address of the output directory
        amr_sequences_file: the address of the file containing the sequence of all AMRs from CARD
        amr_threshold: the threshold for coverage and identity
        core_num: the number of used cores
        ga_extra_args: Additional arguments to be supplied to GraphAligner.
        keep_files: True if intermediate files should be kept, False otherwise.
        debug: True if additional debug files should be created, False otherwise.
    """
    align_dir = os.path.join(output_dir, AMR_DIR_NAME, AMR_ALIGN_DIR)
    os.makedirs(align_dir, exist_ok=True)

    """
    AM: This replaces the original implementation of process_amr_group_and_find
    as it's more efficient to run GraphAligner using GraphAligner with multiple 
    threads instead of multiprocessing workers.
    """
    d_amr_to_path_list = are_there_amrs_in_graph(
        gfa_file=gfa_file,
        output_dir=Path(align_dir),
        threshold=amr_threshold,
        amr_path=amr_sequences_file,
        ga_extra_args=ga_extra_args,
        keep_files=keep_files,
        threads=core_num,
        debug=debug
    )
    if debug:
        try_dump_to_disk(d_amr_to_path_list, Path(align_dir) / 'debug_d_amr_to_path_list.json')

    """
    AM: The original implementation has been moved into the following function.
    This is because the output from GraphAligner is now from a single execution,
    and no longer needs to be concatenated from multiple executions.
    """
    d_amr_to_seq = extract_amr_sequences(amr_sequences_file)
    unique_amr_seqs, unique_amr_infos, unique_amr_paths = get_unique_amr_info(
        d_amr_to_path_list,
        d_amr_to_seq
    )
    if debug:
        try_dump_to_disk(
            [
                {'unique_amr_seqs': s, 'unique_amr_infos': i, 'unique_amr_paths': p}
                for s, i, p in zip(unique_amr_seqs, unique_amr_infos, unique_amr_paths)
            ],
            Path(align_dir) / 'debug_get_unique_amr_info.json'
        )

    # write information (the sequence of found AMRs that don't have overlaped paths with others
    # + the list of groups in each all AMRs have overlaped paths) into files
    unique_amr_files = write_found_amrs_to_disk(
        output_dir=Path(output_dir),
        unique_amr_seqs=unique_amr_seqs,
        unique_amr_infos=unique_amr_infos
    )

    return unique_amr_files, unique_amr_paths


def find_corrsponding_seq_path_file(
        amr_name, sequences_file_names, path_info_file_names, seq_length
):
    """
    To return the name of a sequence file (from sequences_file_names)
    and the name of a path file (from path_info_file_names)
    dedicated to sequences extracted with a given length (seq_length)
    from a given amr sequence (amr_name)
    """
    seq_file = -1
    for file_name in sequences_file_names:
        if SEQ_NAME_PREFIX + amr_name + "_" + str(seq_length) in file_name:
            seq_file = file_name
    path_file = -1
    for file_name in path_info_file_names:
        if SEQ_NAME_PREFIX + amr_name + "_" + str(seq_length) in file_name:
            path_file = file_name
    return seq_file, path_file


def seq_annotation_trim_main(
        params, amr_files, all_seq_info_lists, annotation_files, visualize=False
):
    """
    The core function to filter and remove genes that their coverage difference
    from AMR coverage is above a threshold
    Prameters:
        params: the list of parameters imported from params.py
        amr_files: the list of files containing AMRs
        all_seq_info_lists: the list of annotations of neighborhood sequences extracted from the graph
        annotation_files: the files containing annotation info
        visualize: if True, visualize
    """
    coverage_annotation_list = []
    for i, amr_file in enumerate(amr_files):
        restricted_amr_name = extract_name_from_file_name(amr_file)
        # remove some extracted sequences based on coverage consistency
        annotate_dir = os.path.join(
            params.output_dir,
            ANNOTATION_DIR,
            ANNOTATION_DIR + "_" + str(params.neighbourhood_length),
            "annotation_"
            + restricted_amr_name
            + "_"
            + str(params.neighbourhood_length),
        )
        coverage_annotation = ""
        remained_seqs = []
        if params.coverage_difference > 0:
            (
                coverage_annotation,
                remained_seqs,
            ) = check_coverage_consistency_remove_rest_seq(
                all_seq_info_lists[i],
                params.coverage_difference,
                restricted_amr_name,
                annotate_dir,
            )
        if visualize:
            # create an image presenting the annotations for all sequences
            if coverage_annotation != "":
                visual_annotation_csv = coverage_annotation
            else:
                visual_annotation_csv = annotation_files[i]
            visual_annotation = os.path.join(
                annotate_dir,
                "gene_comparison_"
                + str(params.coverage_difference)
                + "_"
                + restricted_amr_name
                + ".png",
            )
            visualize_annotation(visual_annotation_csv, output=visual_annotation)
        if params.coverage_difference > 0:
            coverage_annotation_list.append(coverage_annotation)
    return coverage_annotation_list


def seq_annotation_main(params, seq_files, path_info_files, amr_files, debug: bool):
    """
    The core function for annotation of neighborhood sequences of all AMRs
    Parameters:
        params: the list of parameters extracted from params.py
        seq_files: the list of neighborhood sequence files
        path_info_files: the list of files containing node info for all sequences
        amr_files: the list of files containing AMRs
        debug: True if additional files should be created, False otherwise.
    Return:

    """
    LOG.info("Neighborhood Annotation...")
    if seq_files:
        neighborhood_files = seq_files
    else:
        LOG.error("No file containing the extracted neighborhood sequences is available!")
        import pdb
        pdb.set_trace()

    if path_info_files:
        nodes_info_files = path_info_files
    else:
        LOG.error("No file containing path info for neighborhood sequences is available!")
        import pdb
        pdb.set_trace()

    all_seq_info_lists = []
    annotation_files = []
    for amr_file in amr_files:
        restricted_amr_name = extract_name_from_file_name(amr_file)
        _, amr_name = retrieve_AMR(amr_file)
        neighborhood_file, nodes_info_file = find_corrsponding_seq_path_file(
            restricted_amr_name,
            neighborhood_files,
            nodes_info_files,
            params.neighbourhood_length,
        )
        if neighborhood_file == -1:
            LOG.error(
                "no sequence file for "
                + amr_file
                + " was found! We looked for a file like "
                + restricted_amr_name
            )
            import pdb

            pdb.set_trace()
            sys.exit(1)
        all_seq_info_list, annotation_file = neighborhood_annotation(
            amr_name,
            neighborhood_file,
            nodes_info_file,
            params.neighbourhood_length,
            params.output_dir,
            params.no_rgi,
            params.rgi_include_loose,
            "_" + restricted_amr_name,
            params.num_cores,
        )
        all_seq_info_lists.append(all_seq_info_list)
        annotation_files.append(annotation_file)

    if debug:
        try_dump_to_disk(
            {'all_seq_info_lists': all_seq_info_lists, 'annotation_files': annotation_files},
            Path(params.output_dir) / 'sequences_info' / 'debug_seq_annotation_main.json'
        )

    return all_seq_info_lists, annotation_files


def sequence_neighborhood_main(
        params,
        gfa_file,
        amr_seq_align_info,
        debug: bool
):
    """
    The core function to extract the neighborhood of AMRs
    Parameters:
        params: the list pf parameters imported from params.py
		bandage_path: the path to bandage executable file
        gfa_file: the file containing the assembly graph
        amr_seq_align_info: the alignment info (AMR alignment in the graph)
    Return:
        the list of files containing extracted sequence and the details of nodes representing them
    """

    # seq_files = []
    # path_info_files = []
    LOG.info(f"Extracting neighborhood sequences with length = {params.neighbourhood_length}")

    # remove paths from GFA file
    # AM: We don't want to modify the users input data so this now goes to a new file
    """
    AM: Since we don't want to modify the users input data, this is now being written
    to a new file in the output directory. This could be in a temporary directory
    instead.
    """
    path_gfa_new = Path(params.output_dir) / f'{gfa_file.stem}_no_paths.gfa'
    delete_lines_started_with("P", gfa_file, path_gfa_new)
    gfa_file = path_gfa_new

    sequence_dir = os.path.join(
        params.output_dir,
        SEQ_DIR_NAME,
        f'{SEQ_DIR_NAME}_{params.neighbourhood_length}',
    )
    os.makedirs(sequence_dir, exist_ok=True)

    # If running single threaded do not add any overhead using multiprocessing pool
    if params.num_cores == 1:
        lists = list()
        for x in amr_seq_align_info:
            lists.append(neighborhood_sequence_extraction(gfa_file,
                                                          params.neighbourhood_length,
                                                          sequence_dir,
                                                          params.min_target_identity,
                                                          SEQ_NAME_PREFIX,
                                                          1000,  # should this really be an option? path_node_threshold
                                                          params.max_kmer_size,
                                                          params.extraction_timeout,
                                                          params.assembler, x))
    else:
        p_extraction = partial(
            neighborhood_sequence_extraction,
            gfa_file,
            params.neighbourhood_length,
            sequence_dir,
            params.min_target_identity,
            SEQ_NAME_PREFIX,
            1000,  # should this really be an option? path_node_threshold
            params.max_kmer_size,
            params.extraction_timeout,
            params.assembler
        )
        with Pool(params.num_cores) as p:
            lists = list(p.imap(p_extraction, amr_seq_align_info))
    seq_files, path_info_files = zip(*lists)

    # AM: To clean up the file we created earlier
    os.remove(path_gfa_new)

    if debug:
        try_dump_to_disk(
            {
                'seq_files': seq_files,
                'path_info_files': path_info_files
            },
            Path(sequence_dir) / 'debug_sequence_neighborhood_main.json'
        )

    return seq_files, path_info_files


def full_pipeline_main(params):
    """
    Main runner function for the sarand workflow
    """
    LOG.info("Starting analysis...")

    # Convert the graph aligner arguments into a consumable dictionary
    ga_extra_args = GraphAlignerParams.from_cli_args(params.ga)

    # extract AMR and alignment information
    LOG.info(f"Finding AMR genes in the assembly graph: {params.input_gfa}")
    unique_amr_files, unique_amr_path_list = find_all_amr_in_graph(
        params.input_gfa,
        params.output_dir,
        params.target_genes,
        params.min_target_identity,
        params.num_cores,
        ga_extra_args,
        params.keep_intermediate_files,
        params.debug
    )

    if not unique_amr_files:
        LOG.error("No AMR genes were found in graph!")
        import pdb
        pdb.set_trace()
        sys.exit(1)

    # not used anywhere? @Somayeh
    send_amr_align_info = False
    if unique_amr_path_list and len(unique_amr_path_list) == len(unique_amr_files):
        send_amr_align_info = True
    else:
        LOG.error("AMR alignment info is not available")
        import pdb

        pdb.set_trace()

    # create pairs of seq and align info
    amr_seq_align_info = []
    for i, amr_file in enumerate(unique_amr_files):
        amr_seq_align_info.append((amr_file, unique_amr_path_list[i]))

    seq_files, path_info_files = sequence_neighborhood_main(
        params,
        params.input_gfa,
        amr_seq_align_info,
        params.debug
    )

    all_seq_info_lists, annotation_file_list = seq_annotation_main(
        params, seq_files, path_info_files, unique_amr_files, params.debug
    )
    # never used? @Somayeh
    coverage_annotation_list = seq_annotation_trim_main(
        params, unique_amr_files, all_seq_info_lists, annotation_file_list, True
    )

    LOG.info("Sarand ran successfully")


def get_unique_amr_info(
        d_amr_to_path_list: Dict[str, List[Dict[str, Any]]],
        d_amr_to_seq: Dict[str, FastaSeq]
):
    """Get the unique AMR sequences and their corresponding paths."""

    """
    AM: This needs to be looked at in more detail, the results from this
    function differ depending on the order that they are iterated over.
    
    The current implementation follows the original ordering (i.e. the order 
    that the AMRs are read from the user input AMR file).
    """
    unique_amr_seqs = []
    unique_amr_infos = []
    unique_amr_paths: List[List[Dict[str, Any]]] = []

    for amr_name, fasta_seq in d_amr_to_seq.items():
        restricted_amr_name = restricted_amr_name_from_modified_name(amr_name)
        if restricted_amr_name not in d_amr_to_path_list:
            continue
        amr_id = fasta_seq.fasta_id
        amr_seq = fasta_seq.seq
        path_info = d_amr_to_path_list[restricted_amr_name]

        overlap, amr_ids = amr_path_overlap(
            found_amr_paths=unique_amr_paths,
            new_paths=path_info,
            new_amr_len=len(amr_seq)  # AM: no longer -1 as seq not ending with '\n'
        )
        if not overlap:
            unique_amr_seqs.append(amr_seq)
            amr_info = {"name": amr_id, "overlap_list": []}
            unique_amr_infos.append(amr_info)
            unique_amr_paths.append(path_info)
        else:
            if len(amr_ids) > 1:
                LOG.error("an AMR has overlap with more than one group")
                import pdb

                pdb.set_trace()
            # add this AMR to the right group of AMRs all having overlaps
            # AM: This will only ever iterate once, or never.
            for cur_id in amr_ids:
                if amr_name not in unique_amr_infos[cur_id]["overlap_list"]:
                    unique_amr_infos[cur_id]["overlap_list"].append(amr_name)

    return unique_amr_seqs, unique_amr_infos, unique_amr_paths


def write_found_amrs_to_disk(
        output_dir: Path,
        unique_amr_seqs,
        unique_amr_infos
):
    amr_dir = output_dir / AMR_DIR_NAME / AMR_SEQ_DIR
    os.makedirs(amr_dir, exist_ok=True)
    overlap_file_name = output_dir / AMR_DIR_NAME / AMR_OVERLAP_FILE

    unique_amr_files = list()

    with overlap_file_name.open('w') as f:
        for i, seq in enumerate(unique_amr_seqs):
            amr_name = amr_name_from_comment(unique_amr_infos[i]["name"])
            restricted_amr_name = restricted_amr_name_from_modified_name(amr_name)
            amr_file = create_fasta_file(
                seq,
                str(amr_dir.absolute()),
                f'>{unique_amr_infos[i]["name"]}',
                restricted_amr_name
            )
            unique_amr_files.append(amr_file)
            f.write(amr_name + ":")
            if unique_amr_infos[i]["overlap_list"]:
                f.write(
                    ", ".join(e for e in unique_amr_infos[i]["overlap_list"])
                )
                f.write("\n")
            else:
                f.write("\n")
    return unique_amr_files
