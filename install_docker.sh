#!/bin/bash
set -e

# ANSI Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=== Docker & NVIDIA Container Toolkit Installation for WSL ===${NC}"

# 1. Uninstall old versions
echo -e "${GREEN}[1/5] Removing old Docker versions...${NC}"
sudo apt-get remove -y docker docker-engine docker.io containerd runc || true

# 2. Setup Repo
echo -e "${GREEN}[2/5] Setting up Docker Repository...${NC}"
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=\"$(dpkg --print-architecture)\" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 3. Install Docker
echo -e "${GREEN}[3/5] Installing Docker Engine...${NC}"
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 4. Install NVIDIA Container Toolkit
echo -e "${GREEN}[4/5] Installing NVIDIA Container Toolkit (for RTX 5060)...${NC}"
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# 5. Configure & Restart
echo -e "${GREEN}[5/5] Configuring Docker...${NC}"
sudo nvidia-ctk runtime configure --runtime=docker
sudo service docker start
ACTUAL_USER=${SUDO_USER:-$USER}
echo "Adding user $ACTUAL_USER to docker group..."
sudo usermod -aG docker $ACTUAL_USER

echo -e "${GREEN}=== Installation Complete! ===${NC}"
echo -e "${BLUE}Please RUN: 'exec newgrp docker' to apply group changes.${NC}"
echo -e "${BLUE}Then verify with: 'docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi'${NC}"
