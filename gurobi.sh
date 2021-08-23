wget https://packages.gurobi.com/9.0/gurobi9.0.2_linux64.tar.gz
sudo mv gurobi9.0.2_linux64.tar.gz /opt
cd /opt;sudo tar xvfz gurobi9.0.2_linux64.tar.gz
cd /opt/gurobi902/linux64/src/build/
sudo make
sudo cp libgurobi_c++.a ../../lib/

# set env var
cat <<EOT >> ~/.bashrc
export GUROBI_HOME="/opt/gurobi902/linux64"
export PATH="\${PATH}:\${GUROBI_HOME}/bin"
export LD_LIBRARY_PATH="\${LD_LIBRARY_PATH}:\${GUROBI_HOME}/lib"
EOT