"""Explicit persistence operations shared by SQL and Cloud Firestore.

User requirement: use the existing Firebase project's ordinary Firestore database
without a billing account. Keep the SQL implementation available for local use and
regression checks; Firestore must be real primary storage, not a score-only mirror.

Queries below name fields and predicates explicitly. Firestore never interprets SQL
or copies a complete database into an in-memory SQL compatibility layer.
"""
from sqlalchemy import select, delete, update


def find(db, model, filters=(), order=(), limit=None, offset=0):
    """Find records with AND predicates: (field, operator, value)."""
    if getattr(db, 'is_firestore', False):
        return db.find(model, filters, order, limit, offset)
    statement = select(model)
    for field, operator, value in filters:
        column = getattr(model, field)
        predicate = {'==': lambda: column == value, '!=': lambda: column != value,
                     '>': lambda: column > value, '>=': lambda: column >= value,
                     '<': lambda: column < value, '<=': lambda: column <= value,
                     'in': lambda: column.in_(value)}[operator]()
        statement = statement.where(predicate)
    for field, direction in order:
        column = getattr(model, field)
        statement = statement.order_by(column.desc() if direction == 'desc' else column.asc())
    if offset:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    return db.scalars(statement).all()


def first(db, model, filters=(), order=()):
    return next(iter(find(db, model, filters, order, limit=1)), None)


def remove_where(db, model, filters):
    if getattr(db, 'is_firestore', False):
        return db.remove_where(model, filters)
    statement = delete(model)
    for field, operator, value in filters:
        column = getattr(model, field)
        statement = statement.where({'==': lambda: column == value, '!=': lambda: column != value,
                                     '>': lambda: column > value, '<': lambda: column < value,
                                     'in': lambda: column.in_(value)}[operator]())
    return db.execute(statement).rowcount


def change_where(db, model, filters, values):
    """Stage a conditional change. Commit keeps the full operation atomic."""
    if getattr(db, 'is_firestore', False):
        return db.change_where(model, filters, values)
    statement = update(model)
    for field, operator, value in filters:
        column = getattr(model, field)
        statement = statement.where({'==': lambda: column == value, '!=': lambda: column != value,
                                     '>': lambda: column > value, '<': lambda: column < value}[operator]())
    return db.execute(statement.values(**values)).rowcount


def ping(db):
    if getattr(db, 'is_firestore', False):
        return db.ping()
    db.execute(select(1))


def consume_token_id(db, model, token_hash, purpose, at):
    if getattr(db, 'is_firestore', False):
        record = db.get(model, token_hash)
        if not record or record.purpose != purpose or record.expires_at <= at:
            return None
        db.delete(record)
        return record.user_id
    return db.execute(delete(model).where(model.token_hash == token_hash, model.purpose == purpose, model.expires_at > at).returning(model.user_id)).scalar_one_or_none()


def resume_children(db, model, owner_id, order_field='created_at', limit=None, offset=0, resume_id=None, since=None):
    """Owned child/parent pairs; never joins records belonging to another owner."""
    from .db import Resume, now
    if not getattr(db, 'is_firestore', False):
        statement = select(model, Resume).join(Resume, Resume.id == model.resume_id).where(Resume.owner == owner_id, Resume.expires_at > now())
        if hasattr(model, 'owner'):
            statement = statement.where(model.owner == owner_id)
        if resume_id:
            statement = statement.where(Resume.id == resume_id)
        if since:
            statement = statement.where(getattr(model, order_field) >= since)
        statement = statement.order_by(getattr(model, order_field).desc())
        if offset:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        return db.execute(statement).all()
    parents = find(db, Resume, [('owner','==',owner_id),('expires_at','>',now())] + ([('id','==',resume_id)] if resume_id else []))
    by_id = {r.id:r for r in parents}
    if hasattr(model, 'owner'):
        children = find(db, model, [('owner','==',owner_id)])
    else:
        children = [child for parent in parents for child in find(db, model, [('resume_id','==',parent.id)])]
    rows = [(child,by_id[child.resume_id]) for child in children if child.resume_id in by_id and (since is None or getattr(child,order_field) >= since)]
    rows.sort(key=lambda pair:getattr(pair[0],order_field),reverse=True)
    return rows[offset:offset+limit] if limit is not None else rows[offset:]


def conversion_pairs(db, owner_id):
    from .db import DocumentRecord, ConversionJob, now
    if not getattr(db, 'is_firestore', False):
        return db.execute(select(DocumentRecord,ConversionJob).join(ConversionJob,ConversionJob.id==DocumentRecord.job_id).where(DocumentRecord.owner==owner_id,ConversionJob.owner==owner_id,ConversionJob.expires_at>now())).all()
    pairs=[]
    for doc in find(db,DocumentRecord,[('owner','==',owner_id)]):
        job=db.get(ConversionJob,doc.job_id)
        if job and job.owner==owner_id and job.expires_at>now():
            pairs.append((doc,job))
    return pairs
