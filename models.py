from datetime import datetime
import os
import pymysql
from flask import abort
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class _Field:
    def __init__(self, name):
        self.name = name
    def __get__(self, obj, owner):
        return self if obj is None else obj._data.get(self.name)
    def __set__(self, obj, value):
        obj._data[self.name] = value
    def __eq__(self, other): return _Expr(self.name, "=", other)
    def __ne__(self, other): return _Expr(self.name, "!=", other)
    def in_(self, values): return _Expr(self.name, "IN", list(values))
    def desc(self): return _Order(self.name, "DESC")
    def asc(self): return _Order(self.name, "ASC")

class _Expr:
    def __init__(self, field, op, value): self.field,self.op,self.value=field,op,value

class _Order:
    def __init__(self, field, direction): self.field,self.direction=field,direction

class MySQL:
    def __init__(self):
        self.session = _Session(self)
    def connect(self):
        from config import Config
        return pymysql.connect(host=Config.DB_HOST, port=int(Config.DB_PORT),
            user=Config.DB_USER, password=Config.DB_PASSWORD, database=Config.DB_NAME,
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, autocommit=False)
    def execute(self, sql, params=(), fetch=None):
        conn=self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetch=="one": result=cur.fetchone()
                elif fetch=="all": result=cur.fetchall()
                else: result=cur.rowcount
            conn.commit()
            return result
        finally: conn.close()
    def create_all(self):
        from config import Config
        conn=pymysql.connect(host=Config.DB_HOST, port=int(Config.DB_PORT),
            user=Config.DB_USER, password=Config.DB_PASSWORD,
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, autocommit=True)
        try:
            with conn.cursor() as c:
                c.execute(f"CREATE DATABASE IF NOT EXISTS `{Config.DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        finally:
            conn.close()
        conn=self.connect()
        try:
            with conn.cursor() as c:
                schema_path=os.path.join(Config.BASE_DIR,"schema.sql")
                sql=open(schema_path,encoding="utf-8").read()
                for stmt in [x.strip() for x in sql.split(";") if x.strip()]:
                    upper=stmt.upper()
                    if upper.startswith("--"): 
                        lines=stmt.splitlines()
                        stmt="\n".join(line for line in lines if not line.strip().startswith("--")).strip()
                    if not stmt or upper.startswith("CREATE DATABASE") or upper.startswith("USE "):
                        continue
                    c.execute(stmt)
            conn.commit()
        finally: conn.close()

class BaseModel:
    table=""
    fields=()
    id=_Field("id")
    def __init__(self, **kwargs):
        self._data={}
        for f in self.fields: self._data[f]=kwargs.get(f)
        self._new=True
    def __repr__(self): return f"<{type(self).__name__} {self._data.get('id')}>"
    @classmethod
    def _from_row(cls,row):
        o=cls(**row); o._new=False; return o
    def _save(self, conn):
        vals={f:self._data.get(f) for f in self.fields if f!="id"}
        if self._data.get("id") is None:
            cols=", ".join(f"`{k}`" for k in vals)
            marks=", ".join(["%s"]*len(vals))
            with conn.cursor() as c:
                c.execute(f"INSERT INTO `{self.table}` ({cols}) VALUES ({marks})", tuple(vals.values()))
                self._data["id"]=c.lastrowid
            self._new=False
        else:
            sets=", ".join(f"`{k}`=%s" for k in vals)
            with conn.cursor() as c:
                c.execute(f"UPDATE `{self.table}` SET {sets} WHERE id=%s", tuple(vals.values())+(self.id,))
            self._new=False

class Query:
    def __init__(self, model, items=None):
        self.model=model; self._items=items
        self._filters=[]; self._orders=[]; self._limit=None
    def _load(self):
        if self._items is not None: return self._items
        sql=f"SELECT * FROM `{self.model.table}`"
        params=[]
        if self._filters:
            clauses=[]
            for e in self._filters:
                if e.op=="IN":
                    vals=e.value
                    if not vals: clauses.append("1=0"); continue
                    clauses.append(f"`{e.field}` IN ({','.join(['%s']*len(vals))})"); params.extend(vals)
                else:
                    clauses.append(f"`{e.field}` {e.op} %s"); params.append(e.value)
            sql += " WHERE " + " AND ".join(clauses)
        if self._orders:
            sql += " ORDER BY " + ", ".join(f"`{x.field}` {x.direction}" for x in self._orders)
        if self._limit is not None: sql += f" LIMIT {int(self._limit)}"
        rows=db.execute(sql,tuple(params),fetch="all")
        self._items=[self.model._from_row(r) for r in rows]
        return self._items
    def filter_by(self, **kwargs):
        q=self._clone()
        q._filters += [_Expr(k,"=",v) for k,v in kwargs.items()]
        return q
    def filter(self,*exprs):
        q=self._clone(); q._filters += list(exprs); return q
    def order_by(self,*orders):
        q=self._clone()
        q._orders += [o if isinstance(o,_Order) else _Order(o.name,"ASC") for o in orders]
        return q
    def limit(self,n):
        q=self._clone(); q._limit=n; return q
    def _clone(self):
        q=Query(self.model,self._items[:] if self._items is not None else None)
        q._filters=self._filters[:]; q._orders=self._orders[:]; q._limit=self._limit
        return q
    def all(self): return self._load()
    def first(self):
        items=self.limit(1)._load(); return items[0] if items else None
    def count(self): return len(self._load())
    def get(self,id): return self.filter_by(id=id).first()
    def get_or_404(self,id):
        obj=self.get(id)
        if not obj: abort(404)
        return obj

class _Session:
    def __init__(self,db): self.db=db; self.pending=[]; self.deleted=[]
    def add(self,obj):
        if obj not in self.pending: self.pending.append(obj)
    def delete(self,obj):
        self.deleted.append(obj)
    def flush(self):
        self._commit(add_only=True)
    def commit(self):
        self._commit(add_only=False)
    def _commit(self,add_only=False):
        conn=self.db.connect()
        try:
            with conn.cursor() as c:
                for obj in list(self.pending):
                    obj._save(conn)
                    if isinstance(obj,Challenge):
                        for cat_id in getattr(obj,"_category_ids",[]):
                            c.execute("INSERT IGNORE INTO challenge_categories (challenge_id,category_id) VALUES (%s,%s)",(obj.id,cat_id))
                self.pending.clear()
                if not add_only:
                    # Persist objects modified in memory by updating their rows.
                    for obj in _loaded_objects:
                        if not obj._new and obj not in self.deleted and obj._data.get("id"):
                            obj._save(conn)
                    for obj in self.deleted:
                        if isinstance(obj,Challenge):
                            c.execute("DELETE FROM challenge_categories WHERE challenge_id=%s",(obj.id,))
                            c.execute("DELETE FROM mcq_options WHERE question_id IN (SELECT id FROM mcq_questions WHERE challenge_id=%s)",(obj.id,))
                            c.execute("DELETE FROM mcq_questions WHERE challenge_id=%s",(obj.id,))
                            c.execute("DELETE FROM submissions WHERE challenge_id=%s",(obj.id,))
                        c.execute(f"DELETE FROM `{obj.table}` WHERE id=%s",(obj.id,))
                    self.deleted.clear()
            conn.commit()
        finally: conn.close()

db = MySQL()
_loaded_objects=[]
_old_from_row=BaseModel._from_row
def _track_from_row(cls,row):
    o=_old_from_row.__func__(cls,row); _loaded_objects.append(o); return o
BaseModel._from_row=classmethod(_track_from_row)

class ModelMeta(type):
    def __getattr__(cls,name):
        if name=="query": return Query(cls)
        raise AttributeError(name)

class Category(BaseModel, metaclass=ModelMeta):
    table="categories"; fields=("id","name","scoreboard_frozen")
    id=_Field("id"); name=_Field("name"); scoreboard_frozen=_Field("scoreboard_frozen")
    @property
    def users(self): return User.query.filter_by(category_id=self.id).all()
    @property
    def challenges(self):
        rows=db.execute("SELECT c.* FROM challenges c JOIN challenge_categories cc ON cc.challenge_id=c.id WHERE cc.category_id=%s",(self.id,),fetch="all")
        return [Challenge._from_row(r) for r in rows]

class User(UserMixin, BaseModel, metaclass=ModelMeta):
    table="users"; fields=("id","username","password_hash","name","reg_number","role","category_id","is_blocked","block_reason","total_score","last_submission_at","created_at")
    id=_Field("id"); username=_Field("username"); password_hash=_Field("password_hash"); name=_Field("name"); reg_number=_Field("reg_number")
    role=_Field("role"); category_id=_Field("category_id"); is_blocked=_Field("is_blocked"); block_reason=_Field("block_reason")
    total_score=_Field("total_score"); last_submission_at=_Field("last_submission_at"); created_at=_Field("created_at")
    def set_password(self,p): self.password_hash=generate_password_hash(p)
    def check_password(self,p): return check_password_hash(self.password_hash,p)
    def is_admin(self): return self.role=="admin"
    def is_staff(self): return self.role=="staff"
    def is_student(self): return self.role=="student"
    @property
    def category(self): return Category.query.get(self.category_id) if self.category_id else None
    @property
    def submissions(self): return Submission.query.filter_by(user_id=self.id).all()
    @property
    def violations(self): return AntiCheatLog.query.filter_by(user_id=self.id).all()

class _CategoryCollection:
    def __init__(self,obj): self.obj=obj
    def __iter__(self):
        rows=db.execute("SELECT category_id FROM challenge_categories WHERE challenge_id=%s",(self.obj.id,),fetch="all") if self.obj.id else []
        ids=getattr(self.obj,"_category_ids",[])+[r["category_id"] for r in rows]
        seen=[]; ids=[x for x in ids if not (x in seen or seen.append(x))]
        return iter([Category.query.get(i) for i in ids if Category.query.get(i)])
    def __len__(self): return len(list(iter(self)))
    def __contains__(self,x): return any(c and c.id==x.id for c in self)
    def append(self,cat):
        if self.obj.id:
            db.execute("INSERT IGNORE INTO challenge_categories (challenge_id,category_id) VALUES (%s,%s)",(self.obj.id,cat.id))
        else:
            self.obj._category_ids.append(cat.id)

class Challenge(BaseModel, metaclass=ModelMeta):
    table="challenges"; fields=("id","title","description","type","points","is_active","created_at","flag_hash","attachment_path","buggy_code","expected_output","language","time_limit_seconds")
    id=_Field("id"); title=_Field("title"); description=_Field("description"); type=_Field("type"); points=_Field("points")
    is_active=_Field("is_active"); created_at=_Field("created_at"); flag_hash=_Field("flag_hash"); attachment_path=_Field("attachment_path")
    buggy_code=_Field("buggy_code"); expected_output=_Field("expected_output"); language=_Field("language"); time_limit_seconds=_Field("time_limit_seconds")
    def __init__(self,**kwargs):
        super().__init__(**kwargs); self._category_ids=[]
    @property
    def categories(self): return _CategoryCollection(self)
    @property
    def mcq_questions(self): return MCQQuestion.query.filter_by(challenge_id=self.id).all()
    @property
    def submissions(self): return Submission.query.filter_by(challenge_id=self.id).all()
    def set_flag(self,raw): self.flag_hash=generate_password_hash(raw.strip())
    def check_flag(self,raw): return bool(self.flag_hash) and check_password_hash(self.flag_hash,raw.strip())

class MCQQuestion(BaseModel, metaclass=ModelMeta):
    table="mcq_questions"; fields=("id","challenge_id","question_text","points","order_index")
    id=_Field("id"); challenge_id=_Field("challenge_id"); question_text=_Field("question_text"); points=_Field("points"); order_index=_Field("order_index")
    @property
    def options(self): return MCQOption.query.filter_by(question_id=self.id).all()

class MCQOption(BaseModel, metaclass=ModelMeta):
    table="mcq_options"; fields=("id","question_id","option_text","is_correct")
    id=_Field("id"); question_id=_Field("question_id"); option_text=_Field("option_text"); is_correct=_Field("is_correct")

class MCQAnswer(BaseModel, metaclass=ModelMeta):
    table="mcq_answers"; fields=("id","user_id","question_id","selected_option_id","is_correct","points_awarded","answered_at")
    id=_Field("id"); user_id=_Field("user_id"); question_id=_Field("question_id"); selected_option_id=_Field("selected_option_id")
    is_correct=_Field("is_correct"); points_awarded=_Field("points_awarded"); answered_at=_Field("answered_at")

class Submission(BaseModel, metaclass=ModelMeta):
    table="submissions"; fields=("id","user_id","challenge_id","answer_text","is_correct","points_awarded","submitted_at")
    id=_Field("id"); user_id=_Field("user_id"); challenge_id=_Field("challenge_id"); answer_text=_Field("answer_text"); is_correct=_Field("is_correct")
    points_awarded=_Field("points_awarded"); submitted_at=_Field("submitted_at")
    @property
    def user(self): return User.query.get(self.user_id)

class AntiCheatLog(BaseModel, metaclass=ModelMeta):
    table="anti_cheat_logs"; fields=("id","user_id","violation_type","count_at_time","created_at")
    id=_Field("id"); user_id=_Field("user_id"); violation_type=_Field("violation_type"); count_at_time=_Field("count_at_time"); created_at=_Field("created_at")
    @property
    def user(self): return User.query.get(self.user_id)

class ChatMessage(BaseModel, metaclass=ModelMeta):
    table="chat_messages"; fields=("id","user_id","message","created_at")
    id=_Field("id"); user_id=_Field("user_id"); message=_Field("message"); created_at=_Field("created_at")
    @property
    def user(self): return User.query.get(self.user_id)

class Setting:
    @staticmethod
    def get(key,default=None):
        row=db.execute("SELECT value FROM settings WHERE `key`=%s",(key,),fetch="one")
        return row["value"] if row else default
    @staticmethod
    def set(key,value):
        db.execute("INSERT INTO settings (`key`,`value`) VALUES (%s,%s) ON DUPLICATE KEY UPDATE value=VALUES(value)",(key,value))

DEFAULT_SETTINGS={"event_status":"waiting","chat_enabled":"0","mcq_result_video_url":"","mcq_bgm_url":""}
