from news_db import load_news_db, sample_news, mark_news_as_seen
import datetime

class DummyScratch: pass
class DummyPersona:
    def __init__(self):
        self.scratch = DummyScratch()

p = DummyPersona()
db = load_news_db()  # 默认读取 persona/news/news_db.json

now = datetime.datetime(2025, 12, 1, 8, 0, 0)

picked = []
for _ in range(5):
    n = sample_news(db, p, now, prefer_unseen=True, prefer_today=False)
    picked.append(n["id"])
    mark_news_as_seen(p, n, now)

print("picked:", picked)
print("seen_size:", len(p.scratch.news_seen_ids))
