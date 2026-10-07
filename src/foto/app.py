import asyncio
import os
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Post, get_async_session, create_db_and_tables, User
from .images import imagekit
from .schemas import UserRead, UserCreate, UserUpdate
from .users import auth_backend, fastapi_users, current_active_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)

app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    caption: str = Form(...),
    user : User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            temp_file_path = temp_file.name
            shutil.copyfileobj(file.file, temp_file)

        upload_response = imagekit.files.upload(
                file=open(temp_file_path, "rb"),
                file_name=file.filename,
                use_unique_file_name=True,
                tags=["backend_upload"]
        )

        if upload_response:
            post = Post(
                user_id=user.id,
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
    session: AsyncSession = Depends(get_async_session),
    user : User = Depends(current_active_user),
):
    result = await session.execute(select(Post).order_by(Post.created_at.desc()))
    posts = [row[0] for row in result.all()]

    result = await session.execute(select(User))
    users = [row[0] for row in result.all()]
    user_dict = {user.id: user.email for user in users}

    posts_data = []

    for post in posts:
        post_data = {
            "id": str(post.id),
            "user_id": str(post.user_id),
            "caption": post.caption,
            "url": post.url,
            "file_type": post.file_type,
            "file_name": post.file_name,
            "created_at": post.created_at.isoformat(),
            "is_owner": post.user_id == user.id,
            "email": user_dict[post.user_id],
        }
        posts_data.append(post_data)
    return {"posts": posts_data}


@app.delete("/post/{post_id}")
async def delete_post(
        post_id: str,
        session: AsyncSession = Depends(get_async_session),
        user : User = Depends(current_active_user),
):

    try:
        post_uuid = uuid.UUID(post_id)
        result = await session.execute(select(Post).where(Post.id == post_uuid))
        post = result.scalars().first()

        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        if post.user_id != user.id:
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action")

        await session.delete(post)
        await session.commit()
        return {"success": True, "message": "Post deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}