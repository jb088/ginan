# Script for auto-downloading the necessary files to run PPP solutions in Ginan
# import boto3
import json
import click
import random
import ftplib
import logging
import requests
import numpy as np
from time import sleep
from pathlib import Path
from typing import Tuple
from copy import deepcopy
import concurrent.futures
from itertools import repeat
from urllib.parse import urlparse
from contextlib import contextmanager
from datetime import datetime, timedelta, date

from gnssanalysis.gn_datetime import GPSDate
from gnssanalysis.gn_download import check_n_download, check_n_download_url, check_file_present

API_URL = "https://data.gnss.ga.gov.au/api"


@contextmanager
def ftp_tls(url: str, **kwargs) -> None:
    kwargs.setdefault("timeout", 30)
    with ftplib.FTP_TLS(url, **kwargs) as ftps:
        ftps.login()
        ftps.prot_p()
        yield ftps
        ftps.quit()


def configure_logging(verbose: bool) -> None:
    if verbose:
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO
    logging.basicConfig(format="%(asctime)s [%(funcName)s] %(levelname)s: %(message)s")
    logging.getLogger().setLevel(logging_level)


def ensure_folders(paths: list) -> None:
    """
    Ensures the list of folders exist in the file system.
    """
    for path in paths:
        if not isinstance(path, Path):
            path = Path(path)
        if not path.is_dir():
            path.mkdir(parents=True)


def generate_nominal_span(start_epoch: datetime, end_epoch: datetime) -> str:
    """
    Generate the 3 character LEN for IGS filename based on the start and end epochs passed in
    """
    span = (end_epoch - start_epoch).total_seconds()
    if span % 86400 == 0.0:
        unit = "D"
        span = int(span // 86400)
    elif span % 3600 == 0.0:
        unit = "H"
        span = int(span // 3600)
    elif span % 60 == 0.0:
        unit = "M"
        span = int(span // 60)
    else:
        raise NotImplementedError

    return f"{span:02}{unit}"


def generate_long_filename(
    analysis_center: str,  # AAA
    content_type: str,  # CNT
    format_type: str,  # FMT
    start_epoch: datetime,
    end_epoch: datetime = None,
    timespan: timedelta = None,
    solution_type: str = "",  # TTT
    sampling_rate: str = "15M",  # SMP
    version: str = "0",  # V
    project: str = "EXP",  # PPP, e.g. EXP, OPS
) -> str:
    """
    Function to generate filename with IGS Long Product Filename convention (v1.0) as outlined in
    http://acc.igs.org/repro3/Long_Product_Filenames_v1.0.pdf

    AAAVPPPTTT_YYYYDDDHHMM_LEN_SMP_CNT.FMT[.gz]
    """
    initial_epoch = start_epoch.strftime("%Y%j%H%M")
    if end_epoch == None:
        end_epoch = start_epoch + timespan
    timespan_str = generate_nominal_span(start_epoch, end_epoch)

    result = (
        f"{analysis_center}{version}{project}"
        f"{solution_type}_"
        f"{initial_epoch}_{timespan_str}_{sampling_rate}_"
        f"{content_type}.{format_type}"
    )
    return result


def generate_content_type(file_ext: str, analysis_center: str) -> str:
    """
    IGS files following the long filename convention require a content specifier
    Given the file extension, generate the content specifier
    """
    file_ext = file_ext.upper()
    file_ext_dict = {
        "ERP": "ERP",
        "SP3": "ORB",
        "CLK": "CLK",
        "OBX": "ATT",
        "TRO": "TRO",
        "SNX": "CRD",
        "BIA": {"ESA": "BIA", None: "OSB"},
    }
    content_type = file_ext_dict.get(file_ext)
    # If result is still dictionary, use analysis_center to determine content_type
    if isinstance(content_type, dict):
        content_type = content_type.get(analysis_center, content_type.get(None))
    return content_type


def generate_sampling_rate(file_ext: str, analysis_center: str, solution_type: str) -> str:
    """
    IGS files following the long filename convention require a content specifier
    Given the file extension, generate the content specifier
    """
    file_ext = file_ext.upper()
    sampling_rates = {
        "ERP": "01D",
        "BIA": "01D",
        "SP3": {
            ("COD", "GFZ", "GRG", "IAC", "JAX", "MIT", "WUM"): "05M",
            ("ESA"): {"FIN": "05M", "RAP": "15M", None: "15M"},
            (): "15M",
        },
        "CLK": {
            ("EMR", "IGS", "MIT", "SHA", "USN"): "05M",
            ("ESA", "GFZ", "GRG"): {"FIN": "30S", "RAP": "05M", None: "30S"},
            (): "30S",
        },
        "OBX": {"GRG": "05M", None: "30S"},
        "TRO": {"JPL": "30S", None: "01H"},
        "SNX": "01D",
    }
    if file_ext in sampling_rates:
        file_rates = sampling_rates[file_ext]
        if isinstance(file_rates, dict):
            for key in file_rates:
                if analysis_center in key:
                    center_rates = file_rates.get(key, file_rates.get(()))
                    break
                else:
                    return file_rates.get(())
            if isinstance(center_rates, dict):
                return center_rates.get(solution_type, center_rates.get(None))
            else:
                return center_rates
        else:
            return file_rates
    else:
        return "01D"


def generate_product_filename(
    reference_start: datetime,
    file_ext: str,
    shift: int = 0,
    long_filename: bool = False,
    AC: str = "IGS",
    timespan: timedelta = timedelta(days=1),
    solution_type: str = "ULT",
    sampling_rate: str = "15M",
    version: str = "0",
    project: str = "OPS",
    content_type: str = None,
) -> Tuple[str, GPSDate, datetime]:
    """
    Generate filename, GPSDate obj from datetime
    Optionally, move reference_start forward by "shift" hours
    """
    reference_start += timedelta(hours=shift)
    if type(reference_start == date):
        gps_date = GPSDate(str(reference_start))
    else:
        gps_date = GPSDate(str(reference_start.date()))

    if long_filename:
        if content_type == None:
            content_type = generate_content_type(file_ext, analysis_center=AC)
        product_filename = (
            generate_long_filename(
                analysis_center=AC,
                content_type=content_type,
                format_type=file_ext,
                start_epoch=reference_start,
                timespan=timespan,
                solution_type=solution_type,
                sampling_rate=sampling_rate,
                version=version,
                project=project,
            )
            + ".gz"
        )
    else:
        if file_ext.lower() == "snx":
            product_filename = f"igs{gps_date.yr[2:]}P{gps_date.gpswk}.snx.Z"
        else:
            hour = f"{reference_start.hour:02}"
            product_filename = f"igu{gps_date.gpswkD}_{hour}.{file_ext}.Z"
    return product_filename, gps_date, reference_start


def download_file_from_cddis(
    filename: str, ftp_folder: str, output_folder: Path, max_retries: int = 3, uncomp: bool = True
) -> None:
    with ftp_tls("gdc.cddis.eosdis.nasa.gov") as ftps:
        ftps.cwd(ftp_folder)
        retries = 0
        download_done = False
        while not download_done and retries <= max_retries:
            try:
                logging.info(f"Attempting Download of: {filename}")
                check_n_download(filename, str(output_folder) + "/", ftps, uncomp=uncomp)
                download_done = True
                logging.info(f"Downloaded {filename}")
            except ftplib.all_errors as e:
                retries += 1
                if retries > max_retries:
                    logging.warning(f"Failed to download {filename} and reached maximum retry count ({max_retries}).")
                    if (output_folder / filename).is_file():
                        (output_folder / filename).unlink()
                    raise e

                logging.debug(f"Received an error ({e}) while try to download {filename}, retrying({retries}).")
                # Add some backoff time (exponential random as it appears to be contention based?)
                sleep(random.uniform(0.0, 2.0**retries))


def download_multiple_files_from_cddis(files: list, ftp_folder: str, output_folder: Path) -> None:
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Wrap this in a list to force iteration of results and so get the first exception if any were raised
        list(executor.map(download_file_from_cddis, files, repeat(ftp_folder), repeat(output_folder)))


def download_product_from_cddis(
    download_dir: Path,
    start_epoch: datetime,
    end_epoch: datetime,
    file_ext: str,
    limit: int = None,
    long_filename: bool = False,
    analysis_center: str = "IGS",
    solution_type: str = "ULT",
    sampling_rate: str = "15M",
    project_type: str = "OPS",
    timespan: timedelta = timedelta(days=2),
) -> None:
    """
    Download the file/s from CDDIS based on start and end epoch, to the
    provided the download directory (download_dir)
    """
    logging.info(f"Attempting CDDIS Product download - {file_ext}")
    logging.info(f"Start Epoch - {start_epoch}")
    logging.info(f"End Epoch - {end_epoch}")
    reference_start = deepcopy(start_epoch)

    if solution_type == "ULT":
        timespan = timedelta(days=2)
    elif solution_type == "RAP":
        timespan = timedelta(days=1)
    product_filename, gps_date, reference_start = generate_product_filename(
        reference_start,
        file_ext,
        long_filename=long_filename,
        AC=analysis_center,
        timespan=timespan,
        solution_type=solution_type,
        sampling_rate=sampling_rate,
        project=project_type,
    )
    logging.info(
        f"Generated filename: {product_filename}, with GPS Date: {gps_date.gpswkD} and reference: {reference_start}"
    )
    out_path = download_dir / product_filename[:-3]
    if out_path.is_file():
        logging.info(f"File {product_filename[:-3]} already present in {download_dir}")
        return
    with ftp_tls("gdc.cddis.eosdis.nasa.gov") as ftps:
        try:
            ftps.cwd(f"gnss/products/{gps_date.gpswk}")
        except ftplib.all_errors as e:
            logging.info(f"{reference_start} too recent")
            logging.info(f"ftp_lib error: {e}")
            product_filename, gps_date, reference_start = generate_product_filename(
                reference_start,
                file_ext,
                shift=-6,
                long_filename=long_filename,
                AC=analysis_center,
                timespan=timespan,
                solution_type=solution_type,
                sampling_rate=sampling_rate,
                project=project_type,
            )
            ftps.cwd(f"gnss/products/{gps_date.gpswk}")

        all_files = ftps.nlst()
        if not (product_filename in all_files):
            logging.info(f"{product_filename} not in gnss/products/{gps_date.gpswk} - too recent")
            raise FileNotFoundError

        # Download File:
        download_file_from_cddis(
            filename=product_filename,
            ftp_folder=f"gnss/products/{gps_date.gpswk}",
            output_folder=download_dir,
        )
        count = 1

        remain = end_epoch - reference_start
        while remain.total_seconds() > timespan.total_seconds():
            if count == limit:
                remain = timedelta(days=0)
            else:
                product_filename, gps_date, reference_start = generate_product_filename(
                    reference_start,
                    file_ext,
                    shift=24,
                    long_filename=long_filename,
                    AC=analysis_center,
                    timespan=timespan,
                    solution_type=solution_type,
                    sampling_rate=sampling_rate,
                    project=project_type,
                )

                # Download File:
                download_file_from_cddis(
                    filename=product_filename,
                    ftp_folder=f"gnss/products/{gps_date.gpswk}",
                    output_folder=download_dir,
                )
                count += 1
                remain = end_epoch - reference_start


def download_atx(download_dir: Path, long_filename: bool = False) -> None:
    """
    Download the ATX, BLQ, GPT-2 files necessary for running the PEA
    provided the download directory (download_dir) and FTP_TLS client object (ftps)
    """

    if long_filename:
        atx_filename = "igs20.atx"
    else:
        atx_filename = "igs14.atx"
    # Get the ATX file if not present already:
    if not (download_dir / f"{atx_filename}").is_file():
        ensure_folders([download_dir])
        url = f"https://files.igs.org/pub/station/general/{atx_filename}"
        logging.info(f"Downloading ATX file - {atx_filename}")
        check_n_download_url(url, str(download_dir))


def download_blq(download_dir: Path) -> None:
    """
    Download the BLQ file necessary for running the PEA
    provided the download directory (download_dir)
    """
    url = "https://peanpod.s3-ap-southeast-2.amazonaws.com/pea/examples/EX03/products/OLOAD_GO.BLQ"
    logging.info(f"Downloading BLQ file")
    check_n_download_url(url, str(download_dir))
    logging.info(f"BLQ file present in {download_dir}")


def download_brdc(
    download_dir: Path,
    start_epoch: datetime,
    end_epoch: datetime,
    source: str = "cddis",
    rinexVersion: str = "2",
    filePeriod: str = "01D",
) -> None:
    """
    Download the most recent BRDC file/s from CDDIS
    provided the download directory (download_dir)
    """
    # Download Broadcast file/s
    logging.info("Downloading Broadcast files")
    if source.lower() == "gnss-data":
        download_files_from_gnss_data(
            station_list=["BRDC"],
            start_epoch=start_epoch,
            end_epoch=end_epoch,
            data_dir=download_dir,
            file_period=filePeriod,
            file_type="nav",
            rinex_version=rinexVersion,
        )
    elif source.lower() == "cddis":
        reference_dt = start_epoch - timedelta(days=1)
        while (end_epoch - reference_dt).total_seconds() > 0:
            doy = reference_dt.strftime("%j")
            yr = reference_dt.strftime("%y")
            brdc_compfile = f"brdc{doy}0.{yr}n.gz"
            if check_file_present(brdc_compfile, str(download_dir)):
                logging.info(f"File {brdc_compfile} already present in {download_dir}")
            else:
                download_file_from_cddis(
                    filename=brdc_compfile,
                    ftp_folder=f"gnss/data/daily/{reference_dt.year}/brdc/",
                    output_folder=download_dir,
                )
            reference_dt += timedelta(days=1)


def download_trop_model(download_dir: Path, model: str = "gpt2") -> None:
    """
    Download the relevant troposphere model file/s necessary for running the PEA
    provided the download directory (download_dir) and model
    Default is GPT 2.5
    """
    if model == "gpt2":
        url = "https://peanpod.s3-ap-southeast-2.amazonaws.com/pea/examples/EX03/products/gpt_25.grd"
        check_n_download_url(url, str(download_dir))
        logging.info(f"Troposphere Model files - GPT 2.5 - present in {download_dir}")


def download_most_recent_cddis_file(
    download_dir: Path, pointer_date: GPSDate, file_type: str = "SNX", long_filename: bool = False
) -> None:
    """
    Download the most recent files from IGS provided the download directory (download_dir) session, and file type
    """
    with ftp_tls("gdc.cddis.eosdis.nasa.gov") as ftps:
        # Move to directory of current week:
        ftps.cwd(f"gnss/products/")
        if pointer_date.gpswk not in ftps.nlst():
            GPS_day = int(pointer_date.gpswkD[-1])
            pointer_date = GPSDate(pointer_date.ts - np.timedelta64(7 + GPS_day, "D"))
        ftps.cwd(f"{pointer_date.gpswk}")
        # Search for most recent file
        logging.info(f"Searching for most recent {file_type} files - Long Filename set to: {long_filename}")
        target_filename, pointer_date, ftps = search_for_most_recent_file(
            pointer_date=pointer_date,
            ftps=ftps,
            long_filename=long_filename,
            file_type="SNX",
            analysis_center="IGS",
            timespan=timedelta(days=1),
            solution_type="SNX",
            sampling_rate="01D",
            content_type="CRD",
        )
    # Download recent file:
    download_file_from_cddis(
        filename=target_filename,
        ftp_folder=f"gnss/products/{pointer_date.gpswk}",
        output_folder=download_dir,
    )


def search_for_most_recent_file(
    pointer_date: GPSDate,
    ftps: ftplib.FTP_TLS,
    long_filename: bool = False,
    file_type: str = "SNX",
    analysis_center: str = "IGS",
    timespan: timedelta = timedelta(days=7),
    solution_type: str = "SNX",
    sampling_rate: str = "07D",
    content_type: str = None,
    project_type: str = "OPS",
) -> Tuple[str, GPSDate, ftplib.FTP_TLS]:
    """
    Find the most recent file on CDDIS of file type: file_type
    """
    if content_type == None:
        content_type = generate_content_type(file_type, analysis_center)
    # Get list of available files and those of file type: file_type
    most_recent_files_in_dir = ftps.nlst()
    target_filename, pointer_date, _ = generate_product_filename(
        reference_start=pointer_date.as_datetime,
        file_ext=file_type,
        long_filename=long_filename,
        AC=analysis_center,
        timespan=timespan,
        solution_type=solution_type,
        sampling_rate=sampling_rate,
        content_type=content_type,
        project=project_type,
    )
    file_list = [f for f in most_recent_files_in_dir if f == target_filename]
    # If no files of file_type available, keep looking back week by week:
    while file_list == []:
        logging.info(f"GPS week {pointer_date.gpswk} too recent")
        logging.info(f"No IGS {file_type} files found in GPS week {pointer_date.gpswk}")
        logging.info(f"Moving to GPS week {int(pointer_date.gpswk) - 1}")
        # Move pointer_date back and search
        GPS_day = int(pointer_date.gpswkD[-1])
        pointer_date = GPSDate(pointer_date.ts - np.timedelta64(7 + GPS_day, "D"))
        target_filename, _, _ = generate_product_filename(
            reference_start=pointer_date.as_datetime,
            file_ext=file_type,
            long_filename=long_filename,
            AC=analysis_center,
            timespan=timespan,
            solution_type=solution_type,
            sampling_rate=sampling_rate,
            content_type=content_type,
            project=project_type,
        )
        # pointer_date = GPSDate(np.datetime64(reference_epoch))
        logging.info(f"Searching for file: {target_filename}")
        ftps.cwd("../" + pointer_date.gpswk)
        most_recent_files_in_dir = ftps.nlst()
        file_list = [f for f in most_recent_files_in_dir if f == target_filename]
    logging.info("Found IGS file")
    return target_filename, pointer_date, ftps


def available_stations_at_cddis(start_epoch: datetime, end_epoch: datetime) -> list:
    with ftp_tls("gdc.cddis.eosdis.nasa.gov") as ftps:
        avail_list = []

        start_date = GPSDate(start_epoch.date().isoformat())
        end_date = GPSDate((end_epoch - timedelta(seconds=1)).date().isoformat())

        logging.info("Start date: " + str(start_date))
        logging.info("End date: " + str(end_date))

        date = start_date

        while date.ts <= end_date.ts:
            logging.info("Searching for:" + str(date))
            c_dir = date.yr + "/" + date.dy + "/" + date.yr[-2:] + "d/"
            ftps.cwd(f"/gnss/data/daily/{c_dir}")
            c_list = [x[:4] for x in ftps.nlst() if x.endswith(".crx.gz")]
            if avail_list == []:
                avail_list = c_list
            else:
                avail_list = list(set(avail_list) & set(c_list))
            date = date.next

        return sorted(avail_list)


def download_daily_rinex_files_from_cddis(station_list: list, target_date: GPSDate, rinex_data_dir: Path) -> None:
    "Given a list of stations, target date and path to place files, download RINEX daily data from CDDIS"
    with ftp_tls("gdc.cddis.eosdis.nasa.gov") as ftps:
        logging.info(f"Downloading daily RINEX data for date: {target_date}")
        c_dir = target_date.yr + "/" + target_date.dy + "/" + target_date.yr[-2:] + "d/"
        ftps.cwd(f"/gnss/data/daily/{c_dir}")
        logging.info(f"Downloading stations: {station_list}")
        day_files = [f for f in ftps.nlst() if f[:4] in station_list]
        # Download
        download_multiple_files_from_cddis(day_files, f"/gnss/data/daily/{c_dir}", rinex_data_dir)


def download_gnss_data_entry(entry: dict, output_dir: Path, max_retries: int = 3) -> str:
    file_url = entry["fileLocation"]
    file_type = entry["fileType"]
    retries = 0
    download_done = False
    if file_type == "obs":
        filename = urlparse(file_url).path.split("/")[-1].split(".")[0] + ".rnx"
    elif file_type == "nav":
        filename = ".".join(urlparse(file_url).path.split("/")[-1].split(".")[:2])
    out_path = output_dir / filename
    if out_path.is_file():
        logging.info(f"File {filename} already present in {output_dir}")
        return filename
    else:
        while not download_done and retries <= max_retries:
            try:
                logging.info(f"Downloading {filename} to {out_path}")
                check_n_download_url(file_url, str(output_dir), filename)
                download_done = True
                logging.info(f"Downloaded {filename}")
                return filename
            except:
                retries += 1
                if retries > max_retries:
                    logging.warning(f"Failed to download {file_url} and reached maximum retry count ({max_retries}).")

                logging.debug(f"Received an error while try to download {file_url}, retrying({retries}).")
                # Add some backoff time (exponential random as it appears to be contention based?)
                sleep(random.uniform(0.0, 2.0**retries))


def download_files_from_gnss_data(
    station_list: list,
    start_epoch: datetime,
    end_epoch: datetime,
    data_dir: Path,
    file_period: str = "01D",
    rinex_version: int = 3,
    file_type: str = "obs",
    decompress: str = "true",
) -> None:
    "Given a list of stations, start and end datetime, and a path to place files, download RINEX data from gnss-data"
    # Parameters for the Query:
    QUERY_PARAMS = {
        "metadataStatus": "valid",
        "stationId": ",".join(station_list),
        "fileType": file_type,
        "rinexVersion": rinex_version,
        "filePeriod": file_period,
        "decompress": decompress,
        "startDate": start_epoch.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDate": end_epoch.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tenantId": "default",
    }
    # Submit Request:
    request = requests.get(API_URL + "/rinexFiles", params=QUERY_PARAMS, headers={})
    request.raise_for_status()
    # Download results:
    files_downloaded = []
    for query_response_item in json.loads(request.content):
        filename = download_gnss_data_entry(entry=query_response_item, output_dir=data_dir, max_retries=3)
        try:
            files_downloaded.append(filename.upper())
        except AttributeError:
            files_downloaded.append(filename)
    stations_downloaded = set([filename[:4] for filename in files_downloaded])
    missing_stations = set(station_list) - stations_downloaded
    logging.info(f"Not downloaded / missing: {list(missing_stations)}")


def long_filename_cddis_cutoff(epoch: datetime) -> bool:
    """
    Simple function that determines whether long filenames should be expected on the CDDIS server
    """
    # Long filename cut-off:
    long_filename_cutoff = datetime(2022, 11, 27)
    if epoch >= long_filename_cutoff:
        return True
    else:
        return False


def auto_download(
    target_dir: Path,
    preset: str,
    station_list: str,
    start_datetime: str,
    end_datetime: str,
    most_recent: bool,
    analysis_center: str,
    atx: bool,
    blq: bool,
    snx: bool,
    nav: bool,
    sp3: bool,
    erp: bool,
    clk: bool,
    bia: bool,
    gpt2: bool,
    product_dir: Path,
    rinex_data_dir: Path,
    trop_dir: Path,
    solution_type: str,
    rinex_file_period: str,
    bia_ac: str,
    datetime_format: str,
    data_source: str,
    verbose: bool,
) -> None:
    configure_logging(verbose)

    # Assign flags for preset selection
    if preset == "real-time":
        most_recent = True
        atx = True
        blq = True
        trop_model = "gpt2"
        snx = True

    if preset == "igs-station":
        station_list = station_list.split(",")
        atx = True
        blq = True
        trop_model = "gpt2"
        snx = True
        nav = True
        sp3 = True
        erp = True
        if solution_type == "RAP":
            clk = True
            bia = True

    if solution_type in ["FIN", "RAP"]:
        timespan = timedelta(days=1)
    elif solution_type == "ULT":
        timespan = timedelta(days=2)

    # Assign start and end datetimes (if provided)
    if start_datetime:
        start_epoch = datetime.strptime(start_datetime, datetime_format)
        start_gpsdate = GPSDate(start_epoch.strftime("%Y-%m-%dT%H:%M"))
        long_filename = long_filename_cddis_cutoff(epoch=start_epoch)

    if end_datetime:
        end_epoch = datetime.strptime(end_datetime, datetime_format)

    # If directories haven't been assigned use default: target-dir
    if not product_dir:
        product_dir = target_dir
    if not rinex_data_dir:
        rinex_data_dir = target_dir
    if not trop_dir:
        trop_dir = target_dir

    if not rinex_file_period:
        rinex_file_period = "01D"

    # Ensure the directories exist:
    dir_list = [product_dir, rinex_data_dir, trop_dir, target_dir]
    ensure_folders(dir_list)

    # Assign variables based on flags
    if gpt2:
        trop_model = "gpt2"
    if most_recent:
        start_gpsdate = GPSDate("today")
        long_filename = long_filename_cddis_cutoff(epoch=datetime.today())

    # Download products based on flags
    if atx:
        download_atx(download_dir=product_dir, long_filename=long_filename)
    if blq:
        download_blq(download_dir=product_dir)
    if trop_model:
        download_trop_model(download_dir=trop_dir, model=trop_model)
    if nav:
        download_brdc(download_dir=product_dir, start_epoch=start_epoch, end_epoch=end_epoch, source=data_source)
    if snx and most_recent:
        download_most_recent_cddis_file(
            download_dir=product_dir, pointer_date=start_gpsdate, file_type="SNX", long_filename=long_filename
        )
    if snx and not most_recent:
        try:
            download_product_from_cddis(
                download_dir=product_dir,
                start_epoch=start_epoch,
                end_epoch=end_epoch,
                file_ext="SNX",
                limit=1,
                long_filename=long_filename,
                analysis_center="IGS",
                solution_type="SNX",
                sampling_rate=generate_sampling_rate(file_ext="SNX", analysis_center="IGS", solution_type="SNX"),
                timespan=timedelta(days=1),
            )
        except FileNotFoundError:
            logging.info(f"Received an error ({FileNotFoundError}) while try to download - date too recent.")
            logging.info(f"Downloading most recent SNX file available.")
            download_most_recent_cddis_file(
                download_dir=product_dir, pointer_date=start_gpsdate, file_type="SNX", long_filename=long_filename
            )
    if sp3:
        download_product_from_cddis(
            download_dir=product_dir,
            start_epoch=start_epoch,
            end_epoch=end_epoch,
            file_ext="SP3",
            limit=None,
            long_filename=long_filename,
            analysis_center=analysis_center,
            solution_type=solution_type,
            sampling_rate=generate_sampling_rate(
                file_ext="SP3", analysis_center=analysis_center, solution_type=solution_type
            ),
            timespan=timespan,
        )
    if erp:
        download_product_from_cddis(
            download_dir=product_dir,
            start_epoch=start_epoch,
            end_epoch=end_epoch,
            file_ext="ERP",
            limit=None,
            long_filename=long_filename,
            analysis_center=analysis_center,
            solution_type=solution_type,
            sampling_rate=generate_sampling_rate(
                file_ext="ERP", analysis_center=analysis_center, solution_type=solution_type
            ),
            timespan=timespan,
        )
    if clk:
        download_product_from_cddis(
            download_dir=product_dir,
            start_epoch=start_epoch,
            end_epoch=end_epoch,
            file_ext="CLK",
            limit=None,
            long_filename=long_filename,
            analysis_center=analysis_center,
            solution_type=solution_type,
            sampling_rate=generate_sampling_rate(
                file_ext="CLK", analysis_center=analysis_center, solution_type=solution_type
            ),
            timespan=timespan,
        )
    if bia:
        download_product_from_cddis(
            download_dir=product_dir,
            start_epoch=start_epoch,
            end_epoch=end_epoch,
            file_ext="BIA",
            limit=None,
            long_filename=long_filename,
            analysis_center=bia_ac,
            solution_type=solution_type,
            sampling_rate=generate_sampling_rate(
                file_ext="BIA", analysis_center=analysis_center, solution_type=solution_type
            ),
            timespan=timespan,
        )
    if station_list:
        # Download RINEX files from gnss-data (if station_list provided)
        download_files_from_gnss_data(
            station_list=station_list,
            start_epoch=start_epoch,
            end_epoch=end_epoch,
            data_dir=rinex_data_dir,
            file_period=rinex_file_period,
            file_type="obs",
        )


@click.command()
@click.option("--target-dir", required=True, help="Directory to place file downloads", type=Path)
@click.option("--preset", help="Choose from: manual, real-time, igs-station", default="manual", type=str)
@click.option(
    "--station-list", help="If igs-station option chosen, provide comma-separated list of IGS stations", type=str
)
@click.option("--start-datetime", help="Start of date-time period to download files for", type=str)
@click.option("--end-datetime", help="End of date-time period to download files for", type=str)
@click.option("--most-recent", help="Set to download latest version of files", default=False, is_flag=True)
@click.option("--analysis-center", help="Analysis center of files to download", default="IGS", type=str)
@click.option("--atx", help="Flag to Download ATX file", default=False, is_flag=True)
@click.option("--blq", help="Flag to Download BLQ file", default=False, is_flag=True)
@click.option("--snx", help="Flag to Download SNX / SSC file", default=False, is_flag=True)
@click.option("--nav", help="Flag to Download navigation / broadcast file/s", default=False, is_flag=True)
@click.option("--sp3", help="Flag to Download SP3 file/s", default=False, is_flag=True)
@click.option("--erp", help="Flag to Download ERP file/s", default=False, is_flag=True)
@click.option("--clk", help="Flag to Download CLK file/s", default=False, is_flag=True)
@click.option("--bia", help="Flag to Download BIA bias file", default=False, is_flag=True)
@click.option("--gpt2", help="Flag to Download GPT 2.5 file", default=False, is_flag=True)
@click.option("--product-dir", help="Directory to Download product files. Default: target-dir", type=Path)
@click.option("--rinex-data-dir", help="Directory to Download RINEX data file/s. Default: target-dir", type=Path)
@click.option("--trop-dir", help="Directory to Download troposphere model file/s. Default: target-dir", type=Path)
@click.option(
    "--solution-type",
    help="The solution type of products to download from CDDIS. 'RAP': rapid, or 'ULT': ultra-rapid. Default: RAP",
    default="RAP",
    type=str,
)
@click.option(
    "--rinex-file-period",
    help="File period of RINEX files to download, e.g. 01D, 01H, 15M. Default: 01D",
    default="01D",
    type=str,
)
@click.option("--bia-ac", help="Analysis center of BIA files to download. Default: COD", default="COD", type=str)
@click.option(
    "--datetime-format",
    help="Format of input datetime string. Default: %Y-%m-%d_%H:%M:%S",
    default="%Y-%m-%d_%H:%M:%S",
    type=str,
)
@click.option(
    "--data-source",
    help="Source of data for Broadcast files: CDDIS or gnss-data. Default: gnss-data",
    default="gnss-data",
    type=str,
)
@click.option("--verbose", is_flag=True)
def auto_download_main(
    target_dir,
    preset,
    station_list,
    start_datetime,
    end_datetime,
    most_recent,
    analysis_center,
    atx,
    blq,
    snx,
    nav,
    sp3,
    erp,
    clk,
    bia,
    gpt2,
    product_dir,
    rinex_data_dir,
    trop_dir,
    solution_type,
    rinex_file_period,
    bia_ac,
    datetime_format,
    data_source,
    verbose,
):

    auto_download(
        target_dir,
        preset,
        station_list,
        start_datetime,
        end_datetime,
        most_recent,
        analysis_center,
        atx,
        blq,
        snx,
        nav,
        sp3,
        erp,
        clk,
        bia,
        gpt2,
        product_dir,
        rinex_data_dir,
        trop_dir,
        solution_type,
        rinex_file_period,
        bia_ac,
        datetime_format,
        data_source,
        verbose,
    )


if __name__ == "__main__":
    auto_download_main()
