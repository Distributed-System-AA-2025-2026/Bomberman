from HubServer import HubServer
from fastapi import FastAPI
app = FastAPI()


@app.get("/")
def read_root():
    return {"content": "Hello world!"}

def main():
    hubServer = HubServer([])


if __name__ == '__main__':
    main()