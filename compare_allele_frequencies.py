#!/usr/bin/env python
"""
This script compares allele frequencies across genetic clades to identify fixed alleles, unique fixed alleles, private alleles, and positions with a single clade.
The script works with .frq files generated by vcftools using the --freq option (NOTE: do not use --freq2 as this will not provide all information needed to run the script).
"""
import argparse
import os
import math

__author__ = 'Dennis van Hulten'
__copyright__ = 'Copyright (C) 2025 Dennis van Hulten'
__license__ = 'GPL'

def process_files(file_list):
    all_alleles = {}

    for file, n_indv in file_list:
        clade_name = file.split('/')[-1].replace('.frq', '')

        with open(file) as f:
            lines = f.readlines()
            header = lines[0].strip().split("\t")

            for line in lines[1:]:
                line = line.strip().split("\t")
                CHROM = line[header.index("CHROM")]
                POS = int(line[header.index("POS")])
                num_alleles = int(line[header.index("N_ALLELES")])
                num_chromosomes = int(line[header.index("N_CHR")])
                genotyped_indv = num_chromosomes / 2

                allele_freqs = {}
                allele_freq_index = header.index("{ALLELE:FREQ}")
                for j in range(num_alleles):
                    allele, freq = line[allele_freq_index + j].split(":")
                    allele_freqs[allele] = float(freq)

                perc_genotyped = genotyped_indv / n_indv
                all_alleles.setdefault((CHROM, POS), {})[clade_name] = (perc_genotyped, allele_freqs)

    return all_alleles

def identify_fixed_alleles(all_alleles, miss_tolerance=1.0, error_tolerance=0):
    fixed_alleles = {}
    for (CHROM, POS), clade_data in all_alleles.items():
        for clade, (perc_genotyped, allele_freqs) in clade_data.items():
            if perc_genotyped >= miss_tolerance and max(allele_freqs.values()) >= 1.0 - error_tolerance:
                fixed_alleles.setdefault((CHROM, POS), []).append((clade, allele_freqs))
    return fixed_alleles

def find_unique_fixed_alleles(fixed_alleles):
    unique_fixed_alleles = {}

    for (CHROM, POS), clade_data in fixed_alleles.items():
        fixed_alleles_per_clade = {}
        for clade, allele_freqs in clade_data:
            fixed_allele = max(allele_freqs, key=allele_freqs.get)
            fixed_alleles_per_clade[clade] = fixed_allele
        
        if len(clade_data) == 1:
            unique_fixed_alleles[(CHROM, POS)] = clade_data
            continue
        
        if len(set(fixed_alleles_per_clade.values())) == len(fixed_alleles_per_clade):
            unique_fixed_alleles[(CHROM, POS)] = clade_data
    
    return unique_fixed_alleles

def identify_private_alleles(all_alleles, error_tolerance=0):
    private_alleles = {}

    for (CHROM, POS), clade_data in all_alleles.items():
        if any(perc_genotyped == 0 or any(math.isnan(freq) for freq in allele_freqs.values()) 
                    for _, (perc_genotyped, allele_freqs) in clade_data.items()):
                continue
        private_alleles_at_pos = {}

        for clade, (perc_genotyped, clade_alleles_freq) in clade_data.items():
            clade_alleles = {allele: freq for allele, freq in clade_alleles_freq.items() if freq > error_tolerance}

            other_clades_alleles = set()
            for other_clade, (_, other_alleles_freq) in clade_data.items():
                if other_clade != clade:
                    other_clades_alleles.update(
                        allele for allele, freq in other_alleles_freq.items() if freq > error_tolerance
                    )

            private_alleles_set = {allele: {"freq": freq, "perc_genotyped": perc_genotyped} for allele, freq in clade_alleles.items()
                                    if allele not in other_clades_alleles}

            if private_alleles_set:
                private_alleles_at_pos[clade] = private_alleles_set

        if private_alleles_at_pos:
            private_alleles[(CHROM, POS)] = private_alleles_at_pos

    return private_alleles

def find_private_sites(all_alleles):
    private_sites = {}
    uniquely_missing_sites ={}

    for (CHROM, POS), clade_data in all_alleles.items():
        genotyped_clades = {clade: perc_genotyped for clade, (perc_genotyped, _) in clade_data.items() if perc_genotyped > 0}
        missing_clades = {clade for clade, (perc_genotyped, _) in clade_data.items() if perc_genotyped == 0}

        if len(genotyped_clades) == 1 and len(missing_clades) > 0:
            genotyped_clade, perc_genotyped = list(genotyped_clades.items())[0]
            private_sites[(CHROM, POS)] = (genotyped_clade, perc_genotyped)

        if len(genotyped_clades) > 1 and len(missing_clades) == 1:
            uniquely_missing_sites[(CHROM, POS)] = genotyped_clades

    return private_sites, uniquely_missing_sites

def compute_divergence_scores(all_alleles):
    divergence_scores = {}

    for (CHROM, POS), clade_data in all_alleles.items():
        clade_freqs = list(clade_data.values())

        if len(clade_freqs) < 2:
            continue

        all_alleles_set = set()
        total_genotyped = 0
        num_clades = len(clade_freqs)

        for perc_genotyped, allele_freqs in clade_freqs:
            all_alleles_set.update(allele_freqs.keys())
            total_genotyped += perc_genotyped

        max_diff = 0
        for allele in all_alleles_set:
            freqs = [clade[1].get(allele, 0.0) for clade in clade_freqs]
            max_diff += max(freqs) - min(freqs)

        avg_genotyped = total_genotyped / num_clades
        divergence_scores[(CHROM, POS)] = (max_diff, avg_genotyped)

    return divergence_scores

def write_most_divergent_loci(divergence_scores, filename, num_div_loci=200):
    filtered_scores = {k: v for k, v in divergence_scores.items() if not math.isnan(float(v[0]))}
    sorted_loci = sorted(filtered_scores.items(), key=lambda x: round(float(x[1][0]), 6), reverse=True)[:num_div_loci]
   
    with open(filename, 'w') as file:
        file.write("Chrom\tPos\tDivergence_Score\tAvg_Perc_Genotyped\n")
        for (CHROM, POS), (score, avg_genotyped) in sorted_loci:
            file.write(f"{CHROM}\t{POS}\t{score:.4f}\t{avg_genotyped:.2f}\n")

def write_fixed_alleles_to_file(fixed_alleles, filename):
    header = "Chrom Pos Clade Allele Freq"
    with open(filename, 'w') as file:
        file.write(header + '\n')
        
        grouped_data = {}
        for (chrom, pos), clade_data in fixed_alleles.items():
            key = (chrom, pos)
            if key not in grouped_data:
                grouped_data[key] = []
            for clade, allele_freqs in clade_data:
                for allele, freq in allele_freqs.items():
                    grouped_data[key].append(f"{clade} {allele} {freq}")
        
        for (chrom, pos), entries in grouped_data.items():
            file.write(f"{chrom} {pos} {' '.join(entries)}\n")

def write_unique_fixed_alleles_to_file(unique_fixed_alleles, filename):
    header = "Chrom Pos Clade Allele Freq"
    with open(filename, 'w') as file:
        file.write(header + '\n')
        
        grouped_data = {}
        for (chrom, pos), clade_data in unique_fixed_alleles.items():
            key = (chrom, pos)
            if key not in grouped_data:
                grouped_data[key] = []
            for clade, allele_freqs in clade_data:
                fixed_allele = max(allele_freqs, key=allele_freqs.get)
                freq = allele_freqs[fixed_allele]
                grouped_data[key].append(f"{clade} {fixed_allele} {freq}")
        
        for (chrom, pos), entries in grouped_data.items():
            file.write(f"{chrom} {pos} {' '.join(entries)}\n")

def write_private_alleles_to_file(private_alleles, filename):
    header = "Chrom Pos Clade Allele Freq Perc_Genotyped"
    with open(filename, 'w') as file:
        file.write(header + '\n')
        
        grouped_data = {}
        for (chrom, pos), clade_data in private_alleles.items():
            key = (chrom, pos)
            if key not in grouped_data:
                grouped_data[key] = []
            for clade, alleles_data in clade_data.items():
                for allele, values in alleles_data.items():
                    grouped_data[key].append(f"{clade} {allele} {values['freq']} {values['perc_genotyped']}")
        
        for (chrom, pos), entries in grouped_data.items():
            file.write(f"{chrom} {pos} {' '.join(entries)}\n")

def write_private_sites_to_file(private_sites, filename):
    header = "Chrom Pos Clade Perc_Genotyped"
    with open(filename, 'w') as file:
        file.write(header + '\n')
        
        grouped_data = {}
        for (chrom, pos), (clade, perc_genotyped) in private_sites.items():
            key = (chrom, pos)
            if key not in grouped_data:
                grouped_data[key] = []
            grouped_data[key].append(f"{clade} {perc_genotyped}")
        
        for (chrom, pos), entries in grouped_data.items():
            file.write(f"{chrom} {pos} {' '.join(entries)}\n")

def write_uniquely_missing_sites_to_file(uniquely_missing_sites, filename):
    header = "Chrom Pos Clade Perc_Genotyped"
    with open(filename, 'w') as file:
        file.write(header + '\n')
        
        grouped_data = {}
        for (chrom, pos), clade_data in uniquely_missing_sites.items():
            key = (chrom, pos)
            if key not in grouped_data:
                grouped_data[key] = []
            for clade, perc_genotyped in clade_data.items():
                grouped_data[key].append(f"{clade} {perc_genotyped}")
        
        for (chrom, pos), entries in grouped_data.items():
            file.write(f"{chrom} {pos} {' '.join(entries)}\n")

def main():
    parser = argparse.ArgumentParser(description='Compare allele frequencies across genetic clades.')
    parser.add_argument('file_list', nargs='+', help='List of input files')
    parser.add_argument('miss_tolerance', type=float, help='Missing data tolerance')
    parser.add_argument('error_tolerance', type=float, help='Error tolerance for fixed allele identification')
    parser.add_argument('out_name', help='Base name for output files')
    parser.add_argument('num_div_loci', type=int, default=200, help='Number of most divergent loci to write to file')
    args = parser.parse_args()

    if len(args.file_list) == 1 and os.path.isfile(args.file_list[0]):
        print("Detected input as a file. Reading from:", args.file_list[0])
        file_list = []
        with open(args.file_list[0], 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) != 2:
                    raise ValueError("Error: Each line in the file list must contain a filename and a number of individuals.")
                file_list.append((parts[0], int(parts[1])))
    else:
        print("Detected input as direct arguments.")
        if len(args.file_list) % 2 != 0:
            raise ValueError("Error: File list must contain pairs of (filename, number of individuals).")
        file_list = [(args.file_list[i], int(args.file_list[i + 1])) for i in range(0, len(args.file_list), 2)]

    all_alleles = process_files(file_list)

    fixed_alleles = identify_fixed_alleles(all_alleles, args.miss_tolerance, args.error_tolerance)
    unique_fixed_alleles = find_unique_fixed_alleles(fixed_alleles)
    private_alleles = identify_private_alleles(all_alleles, args.error_tolerance)
    private_sites, uniquely_missing_sites = find_private_sites(all_alleles)
    divergence_scores = compute_divergence_scores(all_alleles)
    write_most_divergent_loci(divergence_scores, f"{args.out_name}_most_divergent_loci.txt", args.num_div_loci)
    write_fixed_alleles_to_file(fixed_alleles, f"{args.out_name}_fixed_alleles.txt")
    write_unique_fixed_alleles_to_file(unique_fixed_alleles, f"{args.out_name}_unique_fixed_alleles.txt")
    write_private_alleles_to_file(private_alleles, f"{args.out_name}_private_alleles.txt")
    write_private_sites_to_file(private_sites, f"{args.out_name}_private_sites.txt")
    if len(file_list) > 2:
        print("More than 2 clades: writing uniquely missing sites to file.")
        write_uniquely_missing_sites_to_file(uniquely_missing_sites, f"{args.out_name}_uniquely_missing_sites.txt")

    print("Files written successfully.")

if __name__ == '__main__':
    main()

