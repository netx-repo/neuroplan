# set env var
cat <<EOT >> ~/.bashrc
export GUROBI_HOME="/scratch/gpfs/ia3026/comp561/neuroplan/gurobi902/linux64"
export PATH="\${PATH}:\${GUROBI_HOME}/bin"
export LD_LIBRARY_PATH="\${LD_LIBRARY_PATH}:\${GUROBI_HOME}/lib"
EOT