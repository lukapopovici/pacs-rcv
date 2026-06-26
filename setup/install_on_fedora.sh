#setup script for fedora with fallback to building from source if pgvector package is not available
#!/bin/bash
set -e

# Update system
sudo dnf update -y

# Install PostgreSQL and development tools
sudo dnf install -y \
    postgresql-server \
    postgresql-contrib \
    postgresql-devel \
    gcc \
    gcc-c++ \
    make \
    git

# Initialize PostgreSQL (safe to run once)
sudo postgresql-setup --initdb || true

# Enable and start PostgreSQL
sudo systemctl enable --now postgresql

# Try to install pgvector from Fedora repositories
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

# Create the database if it doesn't already exist
sudo -u postgres createdb msvmed 2>/dev/null || true

# Enable the vector extension
sudo -u postgres psql -d msvmed -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Show installed extensions
sudo -u postgres psql -d msvmed -c "\dx"

echo ""
echo "========================================="
echo "Setup complete!"
echo "========================================="