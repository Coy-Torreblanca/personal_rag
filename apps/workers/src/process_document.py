import modal

APP_NAME = "s3-docling-ocr-pipeline"
CACHE_DIR = "/root/.cache/docling"
docling_volume = modal.Volume.from_name(
    f"{APP_NAME}_docling_cache_volume", create_if_missing=True
)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgomp1")
    .pip_install(
        "docling>=2.0.0",
        "torch",
        "torchvision",
        "httpx",
        extra_options="--extra-index-url www.download.pytorch.org/whl/cpu",
    )
    .env({"HF_HOME": CACHE_DIR})
)

app = modal.App(APP_NAME, image=image)


@app.cls(
    gpu=None, cpu=2.0, memory=4096, volumes={CACHE_DIR: docling_volume}, timeout=600
)
class DoclingParser:
    @modal.enter()
    def load_modals(self):
        from docling.document_converter import DocumentConverter

        print("Initializing docling document converter.")

        self.converter = DocumentConverter()

        print("Converter successfully initialized")

    @modal.method()
    def process_document(self, download_url: str, upload_url: str):
        import httpx

        print("Processing with Docling pipeline.")

        # TODO upload to url.
        try:
            result = self.converter.convert(download_url)
            markdown_content = result.document.export_to_markdown()
        except Exception as e:
            return {"status": "error", "message": f"failed to fetch s3 obj: {str(e)}"}

        print(f"Document has been processed.")

        # 2. Upload the Markdown string to the presigned S3 upload URL via PUT
        try:
            # S3 presigned URLs require the payload as raw bytes or file-like objects
            upload_response = httpx.put(
                upload_url,
                content=markdown_content.encode("utf-8"),
                headers={"Content-Type": "text/markdown"},
                timeout=60.0,
            )
            upload_response.raise_for_status()
        except Exception as e:
            return {"status": "error", "message": f"failed to upload to S3: {str(e)}"}

        print("Upload complete!")
        return {
            "status": "success",
            "pages": len(result.document.pages)
            if hasattr(result.document, "pages")
            else 1,
        }


@app.function()
def modal_hello_world():
    print("hello world from modal")
    return "modal said hellow world"


@app.function()
def process_document(document_id: str, job_id: str, presigned_url: str):

    print(f"recieved document_id {document_id!r} and {presigned_url!r}")

    return f"recieved document_id {document_id!r} and {presigned_url!r}"


# 4. Local entrypoint to test your deployment
@app.local_entrypoint()
def test_main():

    # replace with url.
    test_url = ""

    parser = DoclingParser()

    response = parser.process_document(test_url)

    from pprint import pprint

    pprint(reponse)
