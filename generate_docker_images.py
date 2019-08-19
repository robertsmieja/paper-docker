import asyncio
import concurrent.futures
import sys
import os
from io import BytesIO

import aiohttp
import docker
from zipfile import ZipFile
from pathlib import Path, PurePosixPath

from docker import DockerClient

API_VERSION = "v1"
PROJECT_NAME_LIST = ["paper", "waterfall", "travertine"]

OUTPUT_DIRECTORY = "./output"
# DOWNLOAD_DIRECTORY = f"{OUTPUT_DIRECTORY}/download"
# GENERATED_DIRECTORY = f"{OUTPUT_DIRECTORY}/generated"

HOST = "https://papermc.io/"

BASE_DOCKER_IMAGE_DICTIONARY = {
    "java8-distroless": "gcr.io/distroless/java:8",
    "java11-distroless": "gcr.io/distroless/java:11",
    "java8-openjdk": "openjdk:8-jdk",
    "java11-openjdk": "openjdk:11-jdk",
    # "java8-openjdk-alpine": "openjdk:8-jdk-alpine",
    # "java11-openjdk-alpine": "openjdk:11-jdk-alpine",
}


async def download_jar(
    build_number, build_download_url, project_name, session, version
):
    download_path = Path(f"{OUTPUT_DIRECTORY}/{project_name}/{version}")

    jar_name = f"{project_name}-{version}-{build_number}.jar"
    jar_path = Path(f"{download_path}/{jar_name}")

    print(f"    Checking... {jar_path}")

    if not (
        jar_path.exists() and jar_path.is_file() and not ZipFile(jar_path).testzip()
    ):
        print(f"  Downloading... {jar_path}")
        async with download_path.mkdir(parents=True, exist_ok=True):
            async with session.get(build_download_url) as build_download_response:
                jar_path.write_bytes(await build_download_response.read())
        print(f"  Downloaded: {jar_path}")

    return jar_path


async def generate_dockerfile(
    build_number: str,
    build_directory_path: Path,
    base_image_name: str,
    base_image_type: str,
    jar_path: Path,
):
    dockerfile_content = f"""FROM {base_image_name}
ADD ["{jar_path.name}", "/"]
ENTRYPOINT ["{jar_path.name}"]"""

    dockerfile = build_directory_path.joinpath(
        f"{base_image_type}.{build_number}.Dockerfile"
    )
    dockerfile.write_text(dockerfile_content)

    return dockerfile


async def build_docker_image(
    dockerfile_path: Path, docker_client: DockerClient, docker_tag: str
):
    [image, logs] = docker_client.images.build(
        fileobj=BytesIO(dockerfile_path.read_bytes()), tag=docker_tag, pull=True
    )
    return image


async def create_image(
    base_image_name,
    base_image_type,
    build_directory_path,
    build_number,
    docker_client,
    jar_path,
    project_name,
    version,
):

    dockerfile_path = await generate_dockerfile(
        build_number, build_directory_path, base_image_name, base_image_type, jar_path
    )

    docker_tag = f"{project_name}:{version}-{build_number}-{base_image_type}"
    # await build_docker_image(dockerfile_path, docker_client, docker_tag)

    # print(f"  Created: {build_directory}")


async def main(docker_client,):
    print("Starting...")

    async with aiohttp.ClientSession() as session:

        for PROJECT_NAME in PROJECT_NAME_LIST:
            project_url = f"{HOST}api/{API_VERSION}/{PROJECT_NAME}"

            async with session.get(project_url) as project_response:
                project_response_json = await project_response.json()

                for version in project_response_json["versions"]:
                    version_url = f"{project_url}/{version}"

                    async with session.get(version_url) as version_response:
                        version_response_json = await version_response.json()

                        build_directory = f"{OUTPUT_DIRECTORY}/{PROJECT_NAME}/{version}"
                        print(f"  Creating... {build_directory}")

                        build_directory_path = Path(build_directory)
                        build_directory_path.mkdir(parents=True, exist_ok=True)

                        all_builds = version_response_json["builds"]["all"]

                        for build_number in all_builds:
                            build_download_url = (
                                f"{version_url}/{build_number}/download"
                            )
                            jar_path = await download_jar(
                                build_number,
                                build_download_url,
                                PROJECT_NAME,
                                session,
                                version,
                            )

                            for (
                                base_image_type,
                                base_image_name,
                            ) in BASE_DOCKER_IMAGE_DICTIONARY.items():

                                await create_image(
                                    base_image_name,
                                    base_image_type,
                                    build_directory_path,
                                    build_number,
                                    docker_client,
                                    jar_path,
                                    PROJECT_NAME,
                                    version,
                                )
                        print(f"  Created: {build_directory}")

    print("Finished!")
    # return asyncio.gather(all_create_image_coroutines)


if __name__ == "__main__":
    assert sys.version_info >= (3, 7), "Script requires Python 3.7+."
    assert os.name is "posix", "Script requires *NIX"
    env_docker_client = docker.from_env()

    event_loop = asyncio.get_event_loop()

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        event_loop.set_default_executor(pool)
        event_loop.run_until_complete(main(env_docker_client))
        # event_loop.run_in_executor(pool, main(docker_client, session))

    # event_loop.run_until_complete(main(docker_client, session))
    # asyncio.run(main(docker_client, session))
