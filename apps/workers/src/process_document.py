import modal

app = modal.App("hello world")


@app.function()
def modal_hello_world():
    print("hello world from modal")
    return "modal said hellow world"
