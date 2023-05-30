import json
import re
import subprocess
from pathlib import Path
from typing import Optional, List

from sarand.config import IS_DOCKER_CONTAINER, DOCKER_BAKTA_ENV, DOCKER_CONDA_EXE, PROGRAM_VERSION_NA
from sarand.util.logger import LOG


class BaktaParams:
    """Interface to the available options when executing Bakta.
    https://github.com/oschwengers/bakta
    """
    __slots__ = (
        'db', 'min_contig_length', 'prefix', 'output', 'genus', 'species',
        'strain', 'plasmid', 'complete', 'prodigal_tf', 'translation_table',
        'gram', 'locus', 'locus_tag', 'keep_contig_headers', 'replicons',
        'compliant', 'proteins', 'meta', 'skip_trna', 'skip_tmrna',
        'skip_rrna', 'skip_ncrna', 'skip_ncrna_region', 'skip_crispr',
        'skip_cds', 'skip_pseudo', 'skip_sorf', 'skip_gap', 'skip_ori',
        'skip_plot', 'verbose', 'debug', 'threads', 'tmp_dir', 'genome'
    )

    def __init__(
            self, genome: Path,
            db: Optional[Path] = None,
            min_contig_length: Optional[int] = None,

            # Input / output
            prefix: Optional[str] = None,
            output: Optional[Path] = None,

            # Organism
            genus: Optional[str] = None,
            species: Optional[str] = None,
            strain: Optional[str] = None,
            plasmid: Optional[str] = None,

            # Annotation
            complete: Optional[bool] = None,
            prodigal_tf: Optional[Path] = None,
            translation_table: Optional[int] = None,
            gram: Optional[str] = None,
            locus: Optional[str] = None,
            locus_tag: Optional[str] = None,
            keep_contig_headers: Optional[bool] = None,
            replicons: Optional[Path] = None,
            compliant: Optional[bool] = None,
            proteins: Optional[Path] = None,
            meta: Optional[bool] = None,

            # Workflow
            skip_trna: Optional[bool] = None,
            skip_tmrna: Optional[bool] = None,
            skip_rrna: Optional[bool] = None,
            skip_ncrna: Optional[bool] = None,
            skip_ncrna_region: Optional[bool] = None,
            skip_crispr: Optional[bool] = None,
            skip_cds: Optional[bool] = None,
            skip_pseudo: Optional[bool] = None,
            skip_sorf: Optional[bool] = None,
            skip_gap: Optional[bool] = None,
            skip_ori: Optional[bool] = None,
            skip_plot: Optional[bool] = None,

            # General
            verbose: Optional[bool] = None,
            debug: Optional[bool] = None,
            threads: Optional[int] = None,
            tmp_dir: Optional[Path] = None,

    ):
        """
        Args:
            genome:  Genome sequences in (zipped) fasta format
            db: Database path (default = <bakta_path>/db). Can also be provided as BAKTA_DB environment variable.
            min_contig_length: Minimum contig size (default = 1; 200 in compliant mode)
            prefix: Prefix for output files
            output: Output directory (default = current working directory)

            genus: Genus name
            species: Species name
            strain: Strain name
            plasmid: Plasmid name

            complete: All sequences are complete replicons (chromosome/plasmid[s])
            prodigal_tf: Path to existing Prodigal training file to use for CDS prediction
            translation_table: Translation table: 11/4 (default = 11)
            gram: Gram type for signal peptide predictions: +/-/? (default = ?)
            locus: Locus prefix (default = 'contig')
            locus_tag: Locus tag prefix (default = autogenerated)
            keep_contig_headers: Keep original contig headers
            replicons: Replicon information table (tsv/csv)
            compliant: Force Genbank/ENA/DDJB compliance
            proteins: Fasta file of trusted protein sequences for CDS annotation
            meta: Run in metagenome mode. This only affects CDS prediction.

            skip_trna: Skip tRNA detection & annotation
            skip_tmrna: Skip tmRNA detection & annotation
            skip_rrna: Skip rRNA detection & annotation
            skip_ncrna: Skip ncRNA detection & annotation
            skip_ncrna_region: Skip ncRNA region detection & annotation
            skip_crispr: Skip CRISPR array detection & annotation
            skip_cds: Skip CDS detection & annotation
            skip_pseudo: Skip pseudogene detection & annotation
            skip_sorf: Skip sORF detection & annotation
            skip_gap: Skip gap detection & annotation
            skip_ori: Skip oriC/oriT detection & annotation
            skip_plot: Skip generation of circular genome plots

            verbose: Print verbose information
            debug: Run Bakta in debug mode. Temp data will not be removed.
            threads: Number of threads to use (default = number of available CPUs)
            tmp_dir: Location for temporary files (default = system dependent auto detection)
        """
        self.genome: Path = genome
        self.db: Optional[Path] = db
        self.min_contig_length: Optional[int] = min_contig_length

        self.prefix: Optional[str] = prefix
        self.output: Optional[Path] = output

        self.genus: Optional[str] = genus
        self.species: Optional[str] = species
        self.strain: Optional[str] = strain
        self.plasmid: Optional[str] = plasmid

        self.complete: Optional[bool] = complete
        self.prodigal_tf: Optional[Path] = prodigal_tf
        self.translation_table: Optional[int] = translation_table
        self.gram: Optional[str] = gram
        self.locus: Optional[str] = locus
        self.locus_tag: Optional[str] = locus_tag
        self.keep_contig_headers: Optional[bool] = keep_contig_headers
        self.replicons: Optional[Path] = replicons
        self.compliant: Optional[bool] = compliant
        self.proteins: Optional[Path] = proteins
        self.meta: Optional[bool] = meta

        self.skip_trna: Optional[bool] = skip_trna
        self.skip_tmrna: Optional[bool] = skip_tmrna
        self.skip_rrna: Optional[bool] = skip_rrna
        self.skip_ncrna: Optional[bool] = skip_ncrna
        self.skip_ncrna_region: Optional[bool] = skip_ncrna_region
        self.skip_crispr: Optional[bool] = skip_crispr
        self.skip_cds: Optional[bool] = skip_cds
        self.skip_pseudo: Optional[bool] = skip_pseudo
        self.skip_sorf: Optional[bool] = skip_sorf
        self.skip_gap: Optional[bool] = skip_gap
        self.skip_ori: Optional[bool] = skip_ori
        self.skip_plot: Optional[bool] = skip_plot

        self.verbose: Optional[bool] = verbose
        self.debug: Optional[bool] = debug
        self.threads: Optional[int] = threads
        self.tmp_dir: Optional[Path] = tmp_dir

    @property
    def path_json(self) -> Path:
        if self.prefix:
            return self.output / f"{self.prefix}.json"
        else:
            return self.output / f"{self.genome.stem}.json"

    @property
    def path_faa(self) -> Path:
        if self.prefix:
            return self.output / f"{self.prefix}.faa"
        else:
            return self.output / f"{self.genome.stem}.faa"

    def as_cmd(self) -> List[str]:
        cmd: List[str] = ['bakta']

        if self.db:
            cmd += ["--db", str(self.db.absolute())]
        if self.min_contig_length:
            cmd += ["--min-contig-length", str(self.min_contig_length)]
        if self.prefix:
            cmd += ["--prefix", str(self.prefix)]
        if self.output:
            cmd += ["--output", str(self.output.absolute())]

        if self.genus:
            cmd += ["--genus", str(self.genus)]
        if self.species:
            cmd += ["--species", str(self.species)]
        if self.strain:
            cmd += ["--strain", str(self.strain)]
        if self.plasmid:
            cmd += ["--plasmid", str(self.plasmid)]

        if self.complete:
            cmd += ["--complete"]
        if self.prodigal_tf:
            cmd += ["--prodigal-tf", str(self.prodigal_tf.absolute())]
        if self.translation_table:
            cmd += ["--translation-table", str(self.translation_table)]
        if self.gram:
            cmd += ["--gram", str(self.gram)]
        if self.locus:
            cmd += ["--locus", str(self.locus)]
        if self.locus_tag:
            cmd += ["--locus-tag", str(self.locus_tag)]
        if self.keep_contig_headers:
            cmd += ["--keep-contig-headers"]
        if self.replicons:
            cmd += ["--replicons", str(self.replicons.absolute())]
        if self.compliant:
            cmd += ["--compliant"]
        if self.proteins:
            cmd += ["--proteins", str(self.proteins.absolute())]
        if self.meta:
            cmd += ["--meta"]

        if self.skip_trna:
            cmd += ["--skip-trna"]
        if self.skip_tmrna:
            cmd += ["--skip-tmrna"]
        if self.skip_rrna:
            cmd += ["--skip-rrna"]
        if self.skip_ncrna:
            cmd += ["--skip-ncrna"]
        if self.skip_ncrna_region:
            cmd += ["--skip-ncrna-region"]
        if self.skip_crispr:
            cmd += ["--skip-crispr"]
        if self.skip_cds:
            cmd += ["--skip-cds"]
        if self.skip_pseudo:
            cmd += ["--skip-pseudo"]
        if self.skip_sorf:
            cmd += ["--skip-sorf"]
        if self.skip_gap:
            cmd += ["--skip-gap"]
        if self.skip_ori:
            cmd += ["--skip-ori"]
        if self.skip_plot:
            cmd += ["--skip-plot"]

        if self.verbose:
            cmd += ["--verbose"]
        if self.debug:
            cmd += ["--debug"]
        if self.threads:
            cmd += ["--threads", str(self.threads)]
        if self.tmp_dir:
            cmd += ["--tmp-dir", str(self.tmp_dir.absolute())]

        cmd.append(str(self.genome.absolute()))
        return cmd


class BaktaResult:
    __slots__ = ('data',)

    def __init__(self, data: dict):
        self.data: dict = data

    def get_for_sarand(self):
        out = list()
        # TODO: Maybe get the sequence from the json too?

        for feature in self.data['features']:
            """
            AM:
            - The Locus tag is different from Prokka
            - Length is off by 1, this is either due to exclusive bounds, or from Bandage?
            - Product name is different (more verbose than prokka)
            - Remove prokka_gene_name once implemented
            - The stop/start are flipped for reverse strand as per the previous implementation
            """
            out.append({
                "locus_tag": feature.get('locus'),
                "gene": feature.get('gene') or '',  # AM: This matches the expected output
                "length": str((feature['stop'] - feature['start']) + 1), # AM: This matches the expected output but should probably remain int
                "product": feature['product'],
                "start_pos": feature['start'] if feature['strand'] == '+' else feature['stop'],
                "end_pos": feature['stop'] if feature['strand'] == '+' else feature['start'],
                "prokka_gene_name": 'TO REMOVE',
                "RGI_prediction_type": None,
                "coverage": None,
                "family": None,
                "seq_value": None,
                "seq_name": None,
                "target_amr": None,
            })
        return out


class Bakta:

    def __init__(self, params: BaktaParams, result: BaktaResult):
        self.params = params
        self.result = result

    @classmethod
    def run(cls, params: BaktaParams):
        cmd = params.as_cmd()

        # If this is being run in the Docker container, then activate the env first
        if IS_DOCKER_CONTAINER:
            cmd = [
                      DOCKER_CONDA_EXE,
                      'run',
                      '-n',
                      DOCKER_BAKTA_ENV,
                  ] + cmd
        LOG.debug(' '.join(map(str, cmd)))
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8'
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"Error running Bakta: {stderr}")

        with params.path_json.open() as f:
            result = BaktaResult(json.load(f))

        return cls(params, result)

    @classmethod
    def run_for_sarand(cls, genome: Path, prefix: str, out_dir: Path):
        params = BaktaParams(
            genome=genome,
            prefix=prefix,
            meta=True,
            skip_trna=True,
            output=out_dir,
        )
        return cls.run(params)

    @staticmethod
    def version() -> str:
        cmd = ['bakta', '--version']
        if IS_DOCKER_CONTAINER:
            cmd = [
                      DOCKER_CONDA_EXE,
                      'run',
                      '-n',
                      DOCKER_BAKTA_ENV,
                  ] + cmd
        LOG.debug(' '.join(map(str, cmd)))
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8'
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"Bakta binary not found.")
        hit = re.match(r'bakta ([\d.]+)', stdout)
        if hit:
            return hit.group(1)
        return PROGRAM_VERSION_NA
