from fastapi import FastAPI
app = FastAPI()

@app.get("/fruits/{fruit_id}")
def read_fruit(fruit_id: int):
    return {"fruit_id": fruit_id, "type": str(type(fruit_id))}

@app.get("/search")
def search(keyword: str | None = None, limit: int = 10):
    return {"keyword": keyword, "limit": limit}