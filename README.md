# ![gn_logo](https://raw.githubusercontent.com/GeoscienceAustralia/ginan/gh-pages/images/GinanLogo273.png)

# Ginan: Software toolkit and service

#### `Ginan v2.1.0`

## Overview

Ginan is a processing package being developed to processes GNSS observations for geodetic applications.  
Further in-depth documentation about its use may be found [here](https://geoscienceaustralia.github.io/ginan/)

We currently support the processing of:

* the United States' Global Positioning System (**GPS**);
* the European Union's Galileo system (**Galileo**);
* the Russian GLONASS system (**GLONASS**)\*;
* the Chinese Navigation Satellite System (**BeiDou**)\*;
* the Japanese QZSS develop system (**QZSS**)\*.

We are actively developing Ginan to have the following capabilities and features:

* Precise Orbit & Clock determination of GNSS satellites (GNSS POD);
* Precise Point Positioning (PPP) of GNSS stations in network and individual mode;
* Real-Time corrections for PPP users;
* Analyse full, single and multi-frequency, multi-GNSS data;
* Delivering atmospheric products such as ionosphere and troposphere models;
* Servicing a wide range of users and receiver types;
* Delivering outputs usable and accessible by non-experts;
* Providing both a real-time and off-line processing capability;
* Delivering both position and integrity information;
* Routinely produce IGS final, rapid, ultra-rapid and real-time (RT) products;
* Model Ocean Tide Loading (OTL) displacements.

The software consists of three main components:
* Network Parameter Estimation Algorithm (PEA) 
* Precise Orbit Determination (POD), and
* Various scripts for combination and analysis of solutions

## Using Ginan with Docker

You can quickly download a ready-to-run Ginan environment using docker by running:

    docker run -it -v ${host_data_folder}:/data gnssanalysis/ginan:v2.1.0 bash

This command connects the `${host_data_folder}` directory on the host (your pc), with the `/data` directory in the container, to allow file access between the two systems, and opens a command line (`bash`) for executing commands.

You will need to have [docker](https://docs.docker.com/get-docker/) installed to use this method.

To verify you have the Ginan executables available once at the Ginan command line, run:

    pea --help


## Installation from source
### Supported Platforms

Ginan is supported and tested on the following platforms

* Linux: tested on Ubuntu 18.04 and 20.04 and 22.04
* MacOS: tested on 10.15 (x86)
* Windows: via docker or WSL on Windows 10 and above

### Dependencies

If instead you wish to build Ginan from source, there are several software dependencies:

* C/C++ and Fortran compiler. We use and recommend [gcc, g++, and gfortran](https://gcc.gnu.org)
* BLAS and LAPACK linear algebra libraries. We use and recommend [OpenBlas](https://www.openblas.net/) as this contains both libraries required
* CMAKE     >  3.0 
* YAML      >  0.6
* Boost     >= 1.73 (tested on 1.73). On Ubuntu 22.04 which uses gcc-11, you need Boost >= 1.74.0
* MongoDB
* Mongo_C   >= 1.71.1
* Mongo_cxx >= 3.6.0 
* Eigen3    >  3.4 
* netCDF4
* Python    >= 3.7

If using gcc verion 11 or about, the minimum version of libraries are:
* Boost     >= 1.74.0
* Mongo_cxx =  3.7.0

Scripts to install dependencies for Ubuntu 18.04/20.04, 22.04, Fedora 38 are available on the `scripts/installation` directory. Users on other system might need to have a look at the `scripts/installation/generic.md` file, which contains the major steps. 

### Mongo

Mongo databases are optionally used to store intermediate data for passing between processes and visualisation. If this functionality is desired please install and start the Mongo service.

### Python

We use Python for automated process (download), postprocessing and visualisation. To use the developed tools, we recommand to use a virtual-environement (or Anaconda equivalent). A requirements file is available in the `scripts/` directory and can be run via
```python
pip3 install -r requirements.txt
```

### Build
Prepare a directory to build in - it's better practice to keep this separated from the source code.
From the Ginan git root directory:

```bash
mkdir -p src/build

cd src/build
cmake ../ 
```    

To build every package simply run `make` or `make -jX` , where X is a number of parallel threads you want to use for the compilation:

```bash
make -j2
```    

Alternatively, to build only a specific package (`pea`, `pod`, `make_otl_blq`, `interpolate_loading`), run as below:

```bash
make pea -j2
```

This should create executables in the `bin` directory of Ginan.

Check to see if you can execute the PEA from the exampleConfigs directory

```
cd ../../exampleConfigs

../bin/pea --help
```    

and you should see something similar to:
```
PEA starting... (main ginan-v2.1.0 from Fri Jun 30 15:15:22 2023)

Options:
  -h [ --help ]                    Help
  -q [ --quiet ]                   Less output
  -v [ --verbose ]                 More output
  -V [ --very-verbose ]            Much more output
           .
           .
           .
  --dump-config-only               Dump the configuration and exit
  --walkthrough                    Run demonstration code interactively with 
                                   commentary

PEA finished
```


Then download all of the example data using the python script provided:

```bash
python3 scripts/s3_filehandler.py -d -p
```   

### Directory Structure

Upon installation, thie ginan directory should have the following structure:

    ginan/
    ├── README.md           ! General README information
    ├── LICENSE.md          ! Software License information
    ├── ChangeLOG.md        ! Release Chnage history
    ├── aws/                ! Amazon Web Services config
    ├── bin/                ! Binary executables directory*
    ├── Docs/               ! Documentation directory
    ├── inputData/          ! Input data for examples **
    │   ├── data/           ! example dataset (rinex files)**
    │   └── products/       ! example products and aux files**
    ├── exampleConfigs      ! Example configuration files
    │   └── Ex20x.yaml      ! 
    ├── lib/                ! Compiled objectlibrary directory*
    ├── scripts/            ! Auxillary Python and Shell scripts and libraries
    └── src/                ! Source code directory
        ├── cpp/            ! Ginan source code
        ├── cmake/   
        ├── doc_templates/
        ├── build/          ! Cmake build directory*
        └── CMakeLists.txt

*\*created during installation process*

*\*\*created by `s3_filehandler.py` script*


## Documentation

Ginan documentation consists of two parts: these documents, and separate doxygen-generated documentation that shows the actual code infrastructure.
It can be found [here](codeDocs/index.html), or generated manually as below.

### Doxygen

The Doxygen documentation for Ginan requires `doxygen` and `graphviz`. If not already installed, type as follows:

```
sudo apt -y install doxygen graphviz
```    

On success, proceed to the build directory and call make with `docs` target:

```
cd ../src/build

cmake ../

make docs
```    

The documentation can then be found at `Docs/codeDocs/index.html`. 

Note that documentation is also generated automatically if `make` is called without arguments and `doxygen` and `graphviz` dependencies are satisfied.


## Ready!
Congratulations! You are now ready to trial the examples from the `exampleConfigs` directory. See Ginan's manual for detailed explanation of each example. Note that examples have relative paths to files in them and rely on the presence of `products` and `data` directories inside the `inputData` directory. Make sure you've run `s3_filehandler.py` from the Build step of these instructions.

The paths are relative to the `exampleConfigs` directory and hence all the examples must be run from the `exampleConfigs` directory.

NB Examples may be configured to use mongoDB. If you have not installed it, please set `mongo: enable` to false in the pea config files.

To run the first example of the PEA:

```
cd ../exampleConfigs

../bin/pea --config ex201.yaml
```    

This should create `outputs/ex201` directory with various `*.trace` files, which contain details about stations processing, a `Network*.trace` file, which contains the results of kalman filtering, and other auxiliary output files as configured in the yamls. 

You can remove the need for path specification to the executable by using the symlink within `exampleConfigs`, or by adding Ginan's bin directory to `~/.bachrc` file:
```
PATH="path_to_ginan_bin:$PATH"
```

## Scripts
In addition to the ginan binaries, [scripts](scripts.index) are available to assist with downloading input files, and viewing and comparing generated outputs.


### Acknowledgements:
We have used routines obtained from RTKLIB, released under a BSD-2 license, these routines have been preserved with modifications in the folder `cpp/src/rtklib`. The original source code from RTKLib can be obtained from https://github.com/tomojitakasu/RTKLIB.

We have used routines obtained from Better Enums, released under the BSD-2 license, these routines have been preserved in the folder `cpp/src/3rdparty` The original source code from Better Enums can be obtained from http://github.com/aantron/better-enums.

We have used routines obtained from EGM96, released under the zlib license, these routines have been preserved in the folder `cpp/src/3rdparty/egm96` The original source code from EGM96 can be obtained from https://github.com/emericg/EGM96.

We have used routines obtained from SOFA, released under the SOFA license, these routines have been preserved in the folder `cpp/src/3rdparty/egm96` The original source code from SOFA can be obtained from https://www.iausofa.org/.

We have used routines obtained from project Pluto, released under the GPL-3 license, these routines have been preserved in the folder `cpp/src/3rdparty/jplephem` The original source code from jpl ephem  can be obtained from https://github.com/Bill-Gray/jpl_eph.
