#
# This Dockerfile for AFLplusplus uses Ubuntu 24.04 and
# installs LLVM 19 for afl-clang-lto support.
#
# GCC 11 is used instead of 12 because genhtml for afl-cov doesn't like it.
#

FROM ubuntu:24.04 AS aflplusplus
LABEL "maintainer"="AFL++ team <afl@aflplus.plus>"
LABEL "about"="AFL++ docker container image"

### Comment out to enable these features
# Only available on specific ARM64 boards
ENV NO_CORESIGHT=1
# Possible but unlikely in a docker container
ENV NO_NYX=1

### Only change these if you know what you are doing:
# Set only to a version that is available in the used Ubuntu released
ENV LLVM_VERSION=20
# GCC 12 is producing compile errors for some targets so we stay at GCC 11
ENV GCC_VERSION=11

### No changes beyond the point unless you know what you are doing :)

ARG DEBIAN_FRONTEND=noninteractive

ENV NO_ARCH_OPT=1
ENV IS_DOCKER=1

RUN apt-get update && apt-get full-upgrade -y && \
    apt-get install -y --no-install-recommends wget ca-certificates apt-utils && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get -y install --no-install-recommends \
    make cmake automake meson ninja-build bison flex \
    git xz-utils bzip2 wget jupp nano bash-completion less vim joe ssh psmisc \
    python3 python3-dev python3-pip python-is-python3 python3-venv \
    libtool libtool-bin libglib2.0-dev \
    apt-transport-https gnupg dialog \
    gnuplot-nox libpixman-1-dev bc \
    gcc-${GCC_VERSION} g++-${GCC_VERSION} gcc-${GCC_VERSION}-plugin-dev gdb lcov \
    clang-${LLVM_VERSION} clang-tools-${LLVM_VERSION} libc++1-${LLVM_VERSION} \
    libc++-${LLVM_VERSION}-dev libc++abi1-${LLVM_VERSION} libc++abi-${LLVM_VERSION}-dev \
    libclang1-${LLVM_VERSION} libclang-${LLVM_VERSION}-dev \
    libclang-common-${LLVM_VERSION}-dev libclang-rt-${LLVM_VERSION}-dev libclang-cpp${LLVM_VERSION} \
    libclang-cpp${LLVM_VERSION}-dev liblld-${LLVM_VERSION} \
    liblld-${LLVM_VERSION}-dev liblldb-${LLVM_VERSION} liblldb-${LLVM_VERSION}-dev \
    libllvm${LLVM_VERSION} libomp-${LLVM_VERSION}-dev libomp5-${LLVM_VERSION} \
    lld-${LLVM_VERSION} lldb-${LLVM_VERSION} llvm-${LLVM_VERSION} \
    llvm-${LLVM_VERSION}-dev llvm-${LLVM_VERSION}-runtime llvm-${LLVM_VERSION}-tools \
    $([ "$(dpkg --print-architecture)" = "amd64" ] && echo gcc-${GCC_VERSION}-multilib gcc-multilib) \
    $([ "$(dpkg --print-architecture)" = "arm64" ] && echo libcapstone-dev) && \
    rm -rf /var/lib/apt/lists/*
    # gcc-multilib is only used for -m32 support on x86
    # libcapstone-dev is used for coresight_mode on arm64

RUN update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-${GCC_VERSION} 0 && \
    update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-${GCC_VERSION} 0 && \
    update-alternatives --install /usr/bin/c++ c++ /usr/bin/g++-${GCC_VERSION} 0 && \
    update-alternatives --install /usr/bin/clang clang /usr/bin/clang-${LLVM_VERSION} 0 && \
    update-alternatives --install /usr/bin/clang++ clang++ /usr/bin/clang++-${LLVM_VERSION} 0

# Needed by unicornafl
RUN wget -qO- https://sh.rustup.rs | CARGO_HOME=/etc/cargo sh -s -- -y -q --no-modify-path
ENV PATH=$PATH:/etc/cargo/bin

RUN apt clean -y

ENV LLVM_CONFIG=llvm-config-${LLVM_VERSION}
ENV AFL_SKIP_CPUFREQ=1
ENV AFL_TRY_AFFINITY=1
ENV AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1

RUN git clone --depth=1 https://github.com/AFLplusplus/cov-analysis && \
    (cd cov-analysis && make install) && rm -rf cov-analysis

WORKDIR /AFLplusplus
COPY . .

# --- DAFLplusplus Additional Setup ---
# Install Z3, tmux, and other packages needed for SVF and fuzzing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libz3-dev z3 tmux libfreetype6 libfreetype6-dev unzip lsb-release software-properties-common

RUN wget https://apt.llvm.org/llvm.sh && \
    chmod +x llvm.sh && \
    ./llvm.sh 21 all && \
    rm llvm.sh

RUN apt-get install -y --no-install-recommends llvm-21-dev libllvm21 clang-21

# Download and install pre-built official SVF-3.3
RUN wget -q https://github.com/SVF-tools/SVF/releases/download/SVF-3.3/SVF-3.3-ubuntu-24.04-x86_64.zip && \
    unzip -q SVF-3.3-ubuntu-24.04-x86_64.zip && \
    mv SVF-linux-x86_64 /opt/svf && \
    rm -rf SVF-3.3-ubuntu-24.04-x86_64.zip __MACOSX

ENV SVF_DIR=/opt/svf
ENV PATH="$SVF_DIR/bin:$PATH"
ENV LD_LIBRARY_PATH="$SVF_DIR/lib:$LD_LIBRARY_PATH"

# Copy and compile the C++ slicer
COPY dafl_svf_slicer.cpp /tmp/dafl_svf_slicer.cpp
RUN clang++ -O3 -std=c++17 /tmp/dafl_svf_slicer.cpp \
    -I/opt/svf/include \
    -L/opt/svf/lib -lSvfLLVM -lSvfCore \
    -Wl,-rpath,/opt/svf/lib \
    $(llvm-config-21 --cxxflags --ldflags --libs) \
    -lz3 -lrt -ldl -lm -pthread -fexceptions \
    -o /usr/local/bin/dafl_svf_slicer && \
    rm /tmp/dafl_svf_slicer.cpp

ARG CC=gcc-$GCC_VERSION
ARG CXX=g++-$GCC_VERSION

# Used in CI to prevent a 'make clean' which would remove the binaries to be tested
ARG TEST_BUILD

RUN python3 -m venv .venv
ENV PATH="/AFLplusplus/.venv/bin:$PATH"

RUN sed -i.bak 's/^	-/	/g' GNUmakefile && \
    make clean && make distrib && \
    ([ "${TEST_BUILD}" ] || (make install)) && \
    mv GNUmakefile.bak GNUmakefile

RUN echo "set encoding=utf-8" > /root/.vimrc && \
    echo ". /etc/bash_completion" >> ~/.bashrc && \
    echo 'alias joe="joe --wordwrap --joe_state -nobackup"' >> ~/.bashrc && \
    echo "export PS1='"'[AFL++ \h] \w \$ '"'" >> ~/.bashrc

# Copy the python wrapper
COPY dafl_svf_slicer.py /usr/local/bin/dafl_svf_slicer.py
RUN chmod +x /usr/local/bin/dafl_svf_slicer.py

# 🌟 --- [新增區塊] GLLVM 安裝與設定 ---
# 下載 Go 官方二進位檔，編譯安裝 gllvm 後卸載 Go 以瘦身鏡像
RUN wget -q https://go.dev/dl/go1.22.2.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.22.2.linux-amd64.tar.gz && \
    rm go1.22.2.linux-amd64.tar.gz

ENV PATH=$PATH:/usr/local/go/bin:/root/go/bin

RUN go install github.com/SRI-CSL/gllvm/cmd/...@latest && \
    rm -rf /usr/local/go

# 這裡先建立一些 gllvm 執行時常用的環境變數預設值（後續進 Container 也能自己蓋掉）
ENV WLLVM_OUTPUT_LEVEL=WARNING

RUN rm -rf /var/lib/apt/lists/*