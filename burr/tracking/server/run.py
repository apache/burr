# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import importlib
import logging
import os
from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Optional, Sequence

from starlette import status

# TODO -- remove this, just for testing
from burr.log_setup import setup_logging
from burr.tracking.server.backend import (
    AnnotationsBackendMixin,
    BackendBase,
    IndexingBackendMixin,
    SnapshottingBackendMixin,
)

setup_logging(logging.INFO)

logger = logging.getLogger(__name__)

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.staticfiles import StaticFiles
    from fastapi_utils.tasks import repeat_every

    from burr.tracking.server import schema
    from burr.tracking.server.schema import (  # AnnotationUpdate,
        AnnotationCreate,
        AnnotationOut,
        AnnotationUpdate,
        ApplicationLogs,
        ApplicationPage,
        BackendSpec,
        IndexingJob,
    )

    # dynamic importing due to the dashes (which make reading the examples on github easier)
    email_assistant = importlib.import_module("burr.examples.email-assistant.server")
    chatbot = importlib.import_module("burr.examples.multi-modal-chatbot.server")
    streaming_chatbot = importlib.import_module("burr.examples.streaming-fastapi.server")
    deep_researcher = importlib.import_module("burr.examples.deep-researcher.server")
    counter = importlib.import_module("burr.examples.hello-world-counter.server")

except ImportError as e:
    raise e
    # require_plugin(
    #     e,
    #     [
    #         "click",
    #         "fastapi",
    #         "uvicorn",
    #         "pydantic",
    #         "fastapi-pagination",
    #         "aiofiles",
    #         "requests",
    #         "jinja2",
    #     ],
    #     "tracking",
    # )

SERVE_STATIC = os.getenv("BURR_SERVE_STATIC", "true").lower() == "true"

SENTINEL_PARTITION_KEY = "__none__"

backend = BackendBase.create_from_env()


# if it is an indexing backend we want to expose a few endpoints


# TODO -- add a health check for intialization


async def sync_index():
    if app_spec.indexing:
        logger.info("Updating backend index...")
        await backend.update()
        logger.info("Updated backend index...")


async def download_snapshot():
    if app_spec.snapshotting:
        logger.info("Downloading snapshot of DB for backend to use")
        await backend.load_snapshot()
        logger.info("Downloaded snapshot of DB for backend to use")


first_snapshot = True


async def save_snapshot():
    # is_first is due to the weirdness of the repeat_every decorator
    # It has to be called but we don't want this to run every time
    # So we just skip the first
    global first_snapshot
    if first_snapshot:
        first_snapshot = False
        return
    if app_spec.snapshotting:
        logger.info("Saving snapshot of DB for recovery")
        await backend.snapshot()
        logger.info("Saved snapshot of DB for recovery")


initialized = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Download if it does it
    # For now we do this before the lifespan
    await download_snapshot()
    # No yield from allowed
    await backend.lifespan(app).__anext__()
    await sync_index()  # this will trigger the repeat every N seconds
    await save_snapshot()  # this will trigger the repeat every N seconds
    global initialized
    initialized = True
    yield
    await backend.lifespan(app).__anext__()


def _get_app_spec() -> BackendSpec:
    """Computes the backend spec from the current backend configuration."""
    is_indexing_backend = isinstance(backend, IndexingBackendMixin)
    is_snapshotting_backend = isinstance(backend, SnapshottingBackendMixin)
    is_annotations_backend = isinstance(backend, AnnotationsBackendMixin)
    supports_demos = backend.supports_demos()
    return BackendSpec(
        indexing=is_indexing_backend,
        snapshotting=is_snapshotting_backend,
        supports_demos=supports_demos,
        supports_annotations=is_annotations_backend,
    )


app_spec = _get_app_spec()

logger = logging.getLogger(__name__)

if app_spec.indexing:
    update_interval = backend.update_interval_milliseconds() / 1000 if app_spec.indexing else None
    sync_index = repeat_every(
        seconds=backend.update_interval_milliseconds() / 1000,
        wait_first=True,
        logger=logger,
    )(sync_index)

if app_spec.snapshotting:
    snapshot_interval = (
        backend.snapshot_interval_milliseconds() / 1000 if app_spec.snapshotting else None
    )
    save_snapshot = repeat_every(
        seconds=backend.snapshot_interval_milliseconds() / 1000,
        wait_first=True,
        logger=logger,
    )(save_snapshot)


def create_burr_ui_app(serve_static: bool = SERVE_STATIC) -> FastAPI:
    """Create a fully-configured Burr UI FastAPI application.

    This factory creates a new FastAPI instance with all Burr UI routes,
    demo routers, and (optionally) static file serving configured.

    :param serve_static: Whether to serve the React UI static files. Defaults to
        the BURR_SERVE_STATIC environment variable (true by default).
    :return: A fully-configured FastAPI application.
    """
    ui_app = FastAPI(lifespan=lifespan)

    @ui_app.get("/ready")
    def is_ready():
        if not initialized:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Backend is not ready yet.",
            )
        return {"ready": True}

    @ui_app.get("/api/v0/metadata/app_spec", response_model=BackendSpec)
    def get_app_spec():
        return _get_app_spec()

    @ui_app.get("/api/v0/projects", response_model=Sequence[schema.Project])
    async def get_projects(request: Request) -> Sequence[schema.Project]:
        """Gets all projects visible by the user.

        :param request: FastAPI request
        :return:  a list of projects visible by the user
        """
        return await backend.list_projects(request)

    @ui_app.get("/api/v0/{project_id}/{partition_key}/apps", response_model=ApplicationPage)
    async def get_apps(
        request: Request,
        project_id: str,
        partition_key: str,
        limit: int = 100,
        offset: int = 0,
    ) -> ApplicationPage:
        """Gets all apps visible by the user

        :param request: FastAPI request
        :param project_id: project name
        :return: a list of projects visible by the user
        """
        if partition_key == SENTINEL_PARTITION_KEY:
            partition_key = None
        applications, total_count = await backend.list_apps(
            request, project_id, partition_key=partition_key, limit=limit, offset=offset
        )
        return ApplicationPage(
            applications=list(applications),
            total=total_count,
            has_another_page=total_count > offset + limit,
        )

    @ui_app.get("/api/v0/{project_id}/{app_id}/{partition_key}/apps")
    async def get_application_logs(
        request: Request, project_id: str, app_id: str, partition_key: str
    ) -> ApplicationLogs:
        """Lists steps for a given App.
        TODO: add streaming capabilities for bi-directional communication
        TODO: add pagination for quicker loading

        :param request: FastAPI
        :param project_id: ID of the project
        :param app_id: ID of the assIndociated application
        :return: A list of steps with all associated step data
        """
        if partition_key == SENTINEL_PARTITION_KEY:
            partition_key = None
        return await backend.get_application_logs(
            request, project_id=project_id, app_id=app_id, partition_key=partition_key
        )

    @ui_app.post(
        "/api/v0/{project_id}/{app_id}/{partition_key}/{sequence_id}/annotations",
        response_model=AnnotationOut,
    )
    async def create_annotation(
        request: Request,
        project_id: str,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        annotation: AnnotationCreate,
    ):
        if partition_key == SENTINEL_PARTITION_KEY:
            partition_key = None
        spec = _get_app_spec()
        if not spec.supports_annotations:
            return []  # empty default -- the case that we don't support annotations
        return await backend.create_annotation(
            annotation, project_id, partition_key, app_id, sequence_id
        )

    #
    # # TODO -- take out these parameters cause we have the annotation ID
    @ui_app.put(
        "/api/v0/{project_id}/{annotation_id}/update_annotations",
        response_model=AnnotationOut,
    )
    async def update_annotation(
        request: Request,
        project_id: str,
        annotation_id: int,
        annotation: AnnotationUpdate,
    ):
        return await backend.update_annotation(
            annotation_id=annotation_id, annotation=annotation, project_id=project_id
        )

    @ui_app.get("/api/v0/{project_id}/annotations", response_model=Sequence[AnnotationOut])
    async def get_annotations(
        request: Request,
        project_id: str,
        app_id: Optional[str] = None,
        partition_key: Optional[str] = None,
        step_sequence_id: Optional[int] = None,
    ):
        # Handle the sentinel value for partition_key
        if partition_key == SENTINEL_PARTITION_KEY:
            partition_key = None
        backend_spec = _get_app_spec()

        if not backend_spec.supports_annotations:
            # makes it easier to wire through to the FE
            return []

        # Logic to retrieve the annotations
        return await backend.get_annotations(project_id, partition_key, app_id, step_sequence_id)

    @ui_app.get("/api/v0/ready")
    async def ready() -> bool:
        return True

    @ui_app.get("/api/v0/indexing_jobs", response_model=Sequence[IndexingJob])
    async def get_indexing_jobs(
        offset: int = 0, limit: int = 100, filter_empty: bool = True
    ) -> Sequence[IndexingJob]:
        if not app_spec.indexing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This backend does not support indexing jobs.",
            )
        return await backend.indexing_jobs(offset=offset, limit=limit, filter_empty=filter_empty)

    @ui_app.get("/api/v0/version")
    async def version() -> dict:
        """Returns the burr version"""
        import pkg_resources

        try:
            burr_version = pkg_resources.get_distribution("apache-burr").version
        except pkg_resources.DistributionNotFound:
            try:
                # Fallback for older installations or development
                burr_version = pkg_resources.get_distribution("burr").version
            except pkg_resources.DistributionNotFound:
                burr_version = "unknown"
        return {"version": burr_version}

    # Examples -- todo -- put them behind `if` statements
    ui_app.include_router(chatbot.router, prefix="/api/v0/chatbot")
    ui_app.include_router(email_assistant.router, prefix="/api/v0/email_assistant")
    ui_app.include_router(streaming_chatbot.router, prefix="/api/v0/streaming_chatbot")
    ui_app.include_router(deep_researcher.router, prefix="/api/v0/deep_researcher")
    ui_app.include_router(counter.router, prefix="/api/v0/counter")

    if serve_static:
        base_asset_directory = str(files("burr").joinpath("tracking/server/build"))
        static_directory = os.path.join(base_asset_directory, "static")

        ui_app.mount(
            "/static",
            StaticFiles(directory=static_directory),
            "/static",
        )
        # public assets in create react app don't get put under build/static,
        # we need to route them over
        ui_app.mount("/public", StaticFiles(directory=base_asset_directory, html=True), "/public")

        # Read index.html once at startup
        with open(os.path.join(base_asset_directory, "index.html")) as f:
            _index_html_template = f.read()

        @ui_app.get("/manifest.json")
        async def manifest_json():
            """Serve manifest.json from the build directory."""
            from starlette.responses import FileResponse

            return FileResponse(
                os.path.join(base_asset_directory, "manifest.json"),
                media_type="application/manifest+json",
            )

        @ui_app.get("/{rest_of_path:path}")
        async def react_app(req: Request, rest_of_path: str):
            """Serves the React app, rewriting asset paths to respect the mount prefix.

            When mounted as a sub-app (e.g. under /burr), the CRA build's hardcoded
            absolute paths (/static/js/..., /api/v0/...) need to be prefixed with the
            mount path so the browser fetches them from the correct location.

            This rewrites both the HTML (href/src attributes) and injects a script that
            sets the OpenAPI client's BASE to the mount prefix, so all API calls are
            also correctly routed.
            """
            from starlette.responses import HTMLResponse

            root_path = req.scope.get("root_path", "")
            if root_path:
                # Rewrite CRA's absolute paths to include the mount prefix
                html = _index_html_template.replace('href="/', f'href="{root_path}/')
                html = html.replace('src="/', f'src="{root_path}/')
                # Inject a script before </head> that patches the OpenAPI BASE config
                # so all runtime API calls (fetch) go to the correct mount path.
                # Also patches image/asset references that use /public/.
                patch_script = f"<script>" f"window.__BURR_BASE_PATH__='{root_path}';" f"</script>"
                html = html.replace("</head>", f"{patch_script}</head>")
            else:
                html = _index_html_template
            return HTMLResponse(html)

    return ui_app


def mount_burr_ui(
    parent_app: FastAPI,
    path: str = "/burr",
    name: str = "burr-ui",
    serve_static: bool = SERVE_STATIC,
) -> FastAPI:
    """Mount the Burr UI inside another FastAPI app.

    :param parent_app: The parent FastAPI application to mount onto.
    :param path: URL path prefix for the Burr UI. Defaults to "/burr".
    :param name: Name for the mounted sub-application. Defaults to "burr-ui".
    :param serve_static: Whether to serve the React UI static files. Defaults to
        the BURR_SERVE_STATIC environment variable (true by default).
    :return: The mounted Burr UI FastAPI app instance.
    """
    ui_app = create_burr_ui_app(serve_static=serve_static)
    parent_app.mount(path, ui_app, name=name)
    return ui_app


# Module-level app for backwards compatibility (used by uvicorn, CLI, etc.)
app = create_burr_ui_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))  # Default to 8000 if no PORT environment variable is set
    uvicorn.run(app, host="0.0.0.0", port=port)
