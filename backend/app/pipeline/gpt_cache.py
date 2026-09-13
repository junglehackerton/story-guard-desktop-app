"""Local cache of validated, exact GPT requests. Never shared across projects."""
import hashlib
import json


class GptRequestCache:
    def __init__(self, database):
        self.database = database

    def key(self, model, effort, prompt, schema):
        payload = json.dumps(['gpt-graph-v2', model, effort, prompt, schema], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, project_id, key):
        with self.database.connect() as db:
            row = db.execute('SELECT response FROM gpt_request_cache WHERE project_id=? AND request_key=?', (project_id, key)).fetchone()
        return row['response'] if row else None

    def put(self, project_id, key, response):
        with self.database.connect() as db:
            db.execute('INSERT OR REPLACE INTO gpt_request_cache(project_id,request_key,response) VALUES(?,?,?)', (project_id, key, response))
            db.execute('''DELETE FROM gpt_request_cache WHERE project_id=? AND rowid NOT IN
                (SELECT rowid FROM gpt_request_cache WHERE project_id=? ORDER BY rowid DESC LIMIT 500)''', (project_id, project_id))

    def delete(self, project_id, key):
        with self.database.connect() as db:
            db.execute('DELETE FROM gpt_request_cache WHERE project_id=? AND request_key=?', (project_id, key))
