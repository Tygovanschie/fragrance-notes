FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY app.py accords.py maintenance.py regions.py notephotos.py catalog.py obf.py pages.py pages_i18n.py pages_home.py gate.py votes.py note_texts.json perfume_photos.json test_api.py test_catalog.py test_obf.py test_pages.py shops.txt ./
EXPOSE 8787
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=4)"
CMD ["python", "app.py"]
