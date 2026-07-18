import modal
from contextlib import contextmanager

app = modal.App("hello world")


@app.function()
def modal_hello_world():
    print("hello world from modal")
    return "modal said hellow world"


@app.function()
def process_document(document_id: str, job_id: str, presigned_url: str):

    print(f"recieved document_id {document_id!r} and {presigned_url!r}")

    return f"recieved document_id {document_id!r} and {presigned_url!r}"
