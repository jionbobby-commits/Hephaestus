from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


# 创建一个 FastAPI 应用实例
app = FastAPI(title="Hephaestus")

#挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_root():
    print("访问根路径")
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

