#!/bin/bash
set -e

sudo dnf update -y

sudo dnf install -y \
    postgresql-server \
    postgresql-contrib \
    postgresql-devel \
    gcc \
    gcc-c++ \
    make \
    git

sudo postgresql-setup --initdb || true

sudo systemctl enable --now postgresql

if dnf search pgvector | grep -qi pgvector; then
    echo "Installing pgvector package..."
    sudo dnf install -y pgvector || \
    sudo dnf install -y postgresql-pgvector || \
    sudo dnf install -y postgresql16-pgvector || true
else
    echo "No pgvector package found. Building from source..."

    cd /tmp

    if [ ! -d pgvector ]; then
        git clone https://github.com/pgvector/pgvector.git
    fi

    cd pgvector
    make
    sudo make install
fi

sudo -u postgres createdb msvmed 2>/dev/null || true

sudo -u postgres psql -d msvmed -c "CREATE EXTENSION IF NOT EXISTS vector;"

sudo -u postgres psql -d msvmed -c "\dx"

echo ""
echo "========================================="
echo "Setup complete!"
echo "========================================="