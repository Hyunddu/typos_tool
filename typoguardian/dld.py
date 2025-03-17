import json
import os
import re
import sys
import requests
from tqdm import tqdm
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, as_completed
from pyxdameraulevenshtein import damerau_levenshtein_distance

current_script_path = os.path.abspath(__file__)
BASE_DIR = os.path.dirname(os.path.dirname(current_script_path))
output_file = os.path.join(BASE_DIR, 'typos_DLD.json')
popular_packages_file = os.path.join(BASE_DIR, 'popular_packages.json')
rss_list_dir = os.path.join(BASE_DIR, 'rss_list')
URL_POPULAR_PACKAGES = "https://hugovk.github.io/top-pypi-packages/top-pypi-packages.min.json"
#update_list_file = os.path.join(BASE_DIR, 'rss_list/mal.json')


def get_latest_update_list_file():
    if not os.path.exists(rss_list_dir):
        os.makedirs(rss_list_dir)
    files = [f for f in os.listdir(rss_list_dir) if os.path.isfile(os.path.join(rss_list_dir, f))]
    json_files = [f for f in files if re.match(r'pypi_update_list\d+\.json', f)]
    json_files.sort(key=lambda x: int(re.search(r'\d+', x).group()), reverse=True)
    return os.path.join(rss_list_dir, json_files[0]) if json_files else None


def preprocess_package(package):
    package = re.sub(r'[<=>!@~`].*', '', package)
    return package.lower().replace('_', '-')


def update_popular_packages():
    try:
        response = requests.get(URL_POPULAR_PACKAGES)
        if response.status_code == 200:
            popular_packages = [pkg['project'] for pkg in response.json()['rows']]
            with open(popular_packages_file, 'w') as file:
                json.dump(popular_packages, file)
            print("Data updated in popular_packages.json")
        else:
            print(f"Error fetching popular packages list: {response.status_code}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")


def load_popular_packages():
    try:
        with open(popular_packages_file, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        print("Popular packages file not found. Please run the script with --update flag to download the file.")
        return []


def load_update_list(json_file):
    try:
        with open(json_file, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"{json_file} not found.")
        return []


def check_hyphen_swapped(package, comparison_package, threshold):
    parts = comparison_package.split('-')
    if len(parts) == 2:
        swapped_package = f"{parts[1]}-{parts[0]}"
        distance = damerau_levenshtein_distance(package, swapped_package)
        max_len = max(len(package), len(swapped_package))
        similarity = 1 - (distance / max_len)
        if similarity > threshold:
            return swapped_package, similarity, True
    return None


def process_package(package_args):
    package, comparison_packages, threshold = package_args
    try:
        matching_packages = {}
        for comparison_package in comparison_packages:
            if package != comparison_package:
                distance = damerau_levenshtein_distance(package, comparison_package)
                max_len = max(len(package), len(comparison_package))
                similarity = 1 - (distance / max_len)
                if similarity > threshold and (comparison_package not in matching_packages or matching_packages[comparison_package][0] < similarity):
                    matching_packages[comparison_package] = (similarity, False)
                swapped_result = check_hyphen_swapped(package, comparison_package, threshold)
                if swapped_result:
                    swapped_package, swapped_similarity, _ = swapped_result
                    if swapped_package not in matching_packages or matching_packages[swapped_package][0] < swapped_similarity:
                        matching_packages[swapped_package] = (swapped_similarity, True)
        return package, matching_packages
    except Exception as e:
        print(f"An error occurred while processing {package}: {str(e)}")
    return None


def save_results(results):
    filtered_results = {}
    for package, matches in results.items():
        filtered_results[package] = []
        seen_typos = set()
        for comparison_package, (score, swapped) in matches.items():
            if comparison_package not in seen_typos:
                filtered_results[package].append([comparison_package, score, swapped])
                seen_typos.add(comparison_package)
            else:
                print(f"Duplicate found and skipped: {comparison_package} in {package}")
    with open(output_file, 'w') as file:
        json.dump(filtered_results, file, indent=4)


def run_dld(update=False, threshold=0.6):
    if update:
        update_popular_packages()

    popular_packages = load_popular_packages()
    if not popular_packages:
        sys.exit("Error: PyPI package names list is empty. Please run the script with --update flag to download the file.")

    update_list_file = get_latest_update_list_file()
    if not update_list_file:
        sys.exit("Error: No update list JSON files found in rss_list directory.")
    update_list = load_update_list(update_list_file)

    filtered_update_list = [pkg for pkg in update_list if pkg not in popular_packages]
    filtered_update_list = [preprocess_package(pkg) for pkg in filtered_update_list]

    results = {}

    with ThreadPoolExecutor(max_workers=mp.cpu_count()) as executor:
        package_args = [(pkg, filtered_update_list, threshold) for pkg in popular_packages]
        futures = {executor.submit(process_package, arg): arg[0] for arg in package_args}

        pbar = tqdm(total=len(popular_packages), desc="Checking packages", unit="package")
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    package, matching_packages = result
                    if matching_packages:
                        results[package] = matching_packages
            except Exception as e:
                print(f"An error occurred while processing: {e}")

            pbar.update(1)

        pbar.close()

    if not results:
        print("임계값 0.6이상인 패키지가 없습니다.")
        sys.exit()

    save_results(results)
    print("Saved: typos_DLD.json")

