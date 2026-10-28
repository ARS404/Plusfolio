"""Bounded synchronization of rebuildable search rows without fetching vectors."""
import hashlib
import unicodedata
from itertools import islice

from django.db import transaction


def normalized(text):
    # Keep case, numbers and operators: they distinguish mathematical problems.
    return ' '.join(unicodedata.normalize('NFC', text).split())


def text_fields(text):
    text = text.strip()
    canonical = normalized(text)
    return {
        'text': text,
        'normalized': canonical.casefold(),
        'fingerprint': hashlib.sha256(canonical.encode()).hexdigest(),
    }


def sync_documents(model, entries, identity, batch_size=100):
    iterator = iter(entries)
    while batch := list(islice(iterator, batch_size)):
        _sync_batch(model, batch, identity)


@transaction.atomic
def _sync_batch(model, entries, identity):
    # Lock in PK order to serialize updates with the encoder's fingerprint check.
    ids = {entry[identity] for entry in entries}
    rows = (model.objects.select_for_update()
            .filter(**{identity + '__in': ids})
            .only('id', identity, 'kind', 'fingerprint').order_by('pk'))
    existing = {(getattr(row, identity), row.kind): row for row in rows}
    created = []
    changed = []
    for entry in entries:
        row = existing.get((entry[identity], entry['kind']))
        if row is None:
            created.append(model(**entry))
        elif row.fingerprint != entry['fingerprint']:
            for field in ['text', 'normalized', 'fingerprint']:
                setattr(row, field, entry[field])
            row.embedding = None
            row.model = ''
            row.retry_at = None
            changed.append(row)
    # Concurrent reconcilers may insert the same missing row; keep its vector.
    if created:
        model.objects.bulk_create(created, ignore_conflicts=True, batch_size=100)
    if changed:
        model.objects.bulk_update(
            changed, ['text', 'normalized', 'fingerprint', 'embedding', 'model', 'retry_at'],
            batch_size=100,
        )
