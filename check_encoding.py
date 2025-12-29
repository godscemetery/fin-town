import glob, json

paths = glob.glob(r"environment/frontend_server/storage/fin_town_test1/personas/*/bootstrap_memory/scratch.json")
print("found", len(paths))
for p in paths:
    try:
        with open(p, "r", encoding="utf-8") as f:
            json.load(f)
        print("OK:", p)
    except Exception as e:
        print("BAD:", p, e)
