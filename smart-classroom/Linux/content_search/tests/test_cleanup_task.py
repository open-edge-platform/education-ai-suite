#
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#

import asyncio

import pytest

from api.v1.endpoints import object as object_endpoint


class _Row:
    def __init__(self, mapping):
        self._mapping = mapping


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self.row = _Row(row) if row is not None else None
        self.statements = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return _Result(self.row)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakeStorage:
    def __init__(self):
        self.exists_calls = []

    def file_exists(self, file_key):
        self.exists_calls.append(file_key)
        return True

    def delete_file(self, file_key):
        raise AssertionError(f"delete_file should not be called for {file_key!r}")


class _FakeSearch:
    def __init__(self):
        self.exists_calls = []

    async def check_file_exists(self, file_path, bucket_name=None):
        self.exists_calls.append(file_path)
        return True

    async def delete_file_index(self, file_path, bucket_name=None):
        raise AssertionError(
            f"delete_file_index should not be called for {file_path!r}"
        )


@pytest.fixture
def services(monkeypatch):
    storage = _FakeStorage()
    search = _FakeSearch()
    monkeypatch.setattr(object_endpoint, "storage_service", storage)
    monkeypatch.setattr(object_endpoint, "search_service", search)
    return storage, search


def test_cleanup_task_without_file_key_deletes_the_row(services):
    storage, search = services
    db = _FakeSession(
        {
            "id": "task-1",
            "payload": '{"bucket": "content-search"}',
            "result": None,
            "status": "COMPLETED",
        }
    )

    response = asyncio.run(object_endpoint.delete_specific_task("task-1", db=db))

    assert response["code"] == 20000
    assert response["data"]["task_id"] == "task-1"
    assert storage.exists_calls == []
    assert search.exists_calls == []
    assert db.committed is True
    delete_calls = [
        params
        for sql, params in db.statements
        if sql.lstrip().upper().startswith("DELETE")
    ]
    assert delete_calls == [{"tid": "task-1"}]


def test_cleanup_task_selects_status_and_refuses_a_processing_task(services):
    storage, search = services
    db = _FakeSession(
        {
            "id": "task-1",
            "payload": "{}",
            "result": None,
            "status": "processing",
        }
    )

    response = asyncio.run(object_endpoint.delete_specific_task("task-1", db=db))

    assert response["code"] == 40000
    assert response["message"] == "Task is still processing"
    assert storage.exists_calls == []
    assert search.exists_calls == []
    assert db.committed is False
    select_sql = db.statements[0][0]
    assert "status" in select_sql.lower()
