from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, Form
from .schemas import PostCreate, PostResponse
from .db import Post, get_async_session, create_db_and_tables
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
from sqlalchemy import select
from .images import imagekit
import asyncio
import os
import shutil
import tempfile


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    caption: str = Form(...),
    session: AsyncSession = Depends(get_async_session)
):
    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            temp_file_path = temp_file.name
            shutil.copyfileobj(file.file, temp_file)

        with open(temp_file_path, "rb") as f:
            upload_response = await asyncio.to_thread(
                imagekit.files.upload,
                file=f,
                file_name=file.filename,
                use_unique_file_name=True,
                tags=["backend_upload"],
            )

        post = Post(
            caption=caption,
            url=upload_response.url,
            file_type="video" if file.content_type.startswith("video/") else "image",
            file_name=upload_response.name
        )
        session.add(post)
        await session.commit()
        await session.refresh(post)
        return {"message": "File uploaded successfully", "post_id": str(post.id)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        file.file.close()


@app.get("/feed")
async def get_feed(
    session: AsyncSession = Depends(get_async_session)
):
    result = await session.execute(select(Post).order_by(Post.created_at.desc()))
    posts = [row[0] for row in result.all()]

    posts_data = []

    for post in posts:
        post_data = {
            "id": str(post.id),
            "caption": post.caption,
            "url": post.url,
            "file_type": post.file_type,
            "file_name": post.file_name,
            "created_at": post.created_at.isoformat()
        }
        posts_data.append(post_data)
    return {"posts": posts_data}