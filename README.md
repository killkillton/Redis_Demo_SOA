# Install Prerequisites

a. Python (3.8 or newer): Download from python.org.

b. Visual Studio Code (VS Code): Download from code.visualstudio.com. (For convenience's sake)

c. Docker Desktop: Download from docker.com.

## 1. Extract and Open the Project(There will be three files)

## 2. Open Visual Studio Code.

## 3. Go to File > Open Folder... and select the extracted folder.

## 4. Open the integrated terminal in VS Code by going to Terminal > New Terminal.

## 5. Set Up the Python Environment

a.Create the virtual environment:

```bash
python -m venv .venv
```

b.Activate the virtual environment:

b1.For Windows:

```bash
.venv\Scripts\activate
```

b2.For macOS/Linux:

```bash
source .venv/bin/activate
```

c.Install the dependencies:

```bash
pip install -r requirements.txt
```

## 6. Start the Redis Server

*Ensure Docker Desktop is running, then execute the following command in the terminal:

```bash
docker compose up -d
```

## 7. Run the FastAPI Server

a.In the terminal, execute:

```bash
uvicorn main:app --reload
```

b.Wait until the terminal outputs that the database is seeded and the application is running on http://127.0.0.1:8000.

## 8. Test the Application

a. Go to http://127.0.0.1:8000/docs for the interactive SwaggerUI

b. Test the search_users_slow with a number and checks the db_time_ms

c. Test the search_users_fast with the same number and checks the db_time_ms(Cache Miss)

d. Test again and see how drastically fast the redis method returns(Cache Hit)

## 9. Shutdown and Cleanup

*When finished, follow these steps to stop the application and clean up the environment:

a. Stop the FastAPI server by clicking into the VS Code terminal and pressing Ctrl + C.

b. Stop and remove the Redis Docker container by running:

```bash
docker compose down
```

## 10. Close Visual Studio Code and Docker Desktop.
