sudo apt install postgresql-16-pgvector

sudo -u postgres psql -d msvmed -c "CREATE EXTENSION IF NOT EXISTS vector;"

sudo apt update

sudo apt-cache search pgvector

sudo -u postgres psql -d msvmed -c "\dx"