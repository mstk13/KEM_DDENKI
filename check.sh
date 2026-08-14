set -x
python manage.py makemigrations --check --dry-run
echo "makemigrations_check_exit=$?"
python manage.py migrate --noinput 2>&1 | tail -8
echo "migrate_exit=$?"
