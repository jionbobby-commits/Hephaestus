from fastapi import FastAPI


app = FastAPI()
@app.get("/")
def read_root():
    return {"message": "Hello!"}


@app.get("/test1")
def read_test1():
    return {"message": "Hello from test1"}


@app.get("/test2")
def read_test2():
    return {"message": "Hello from test2"}