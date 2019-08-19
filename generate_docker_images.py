import asyncio
import collections
import concurrent.futures
import sys

import docker
import requests
from zipfile import ZipFile
from pathlib import Path
from hyper.contrib import HTTP20Adapter

API_VERSION = "v1"
PROJECT_NAME_LIST = ["paper", "waterfall", "travertine"]

OUTPUT_DIRECTORY = "./output"
DOWNLOAD_DIRECTORY = f"{OUTPUT_DIRECTORY}/download"
GENERATED_DIRECTORY = f"{OUTPUT_DIRECTORY}/generated"

HOST = "https://papermc.io/"

BASE_DOCKER_IMAGE_DICTIONARY = {
    "java8-distroless": "gcr.io/distroless/java:8",
    "java11-distroless": "gcr.io/distroless/java:11",
    "java8-openjdk": "openjdk:8-jdk",
    "java11-openjdk": "openjdk:11-jdk",
    # "java8-openjdk-alpine": "openjdk:8-jdk-alpine",
    # "java11-openjdk-alpine": "openjdk:11-jdk-alpine",
}


async def download_jar(project_name, version, build, build_download_url, session):
    download_path = Path(f"{DOWNLOAD_DIRECTORY}/{project_name}/{version}")
    download_path.mkdir(parents=True, exist_ok=True)

    jar_name = f"{project_name}-{version}-{build}.jar"
    jar_path = Path(f"{download_path}/{jar_name}")

    if not (
        jar_path.exists() and jar_path.is_file() and not ZipFile(jar_path).testzip()
    ):
        print(f"  Downloading... {jar_path}")
        build_download_response = session.get(build_download_url)
        jar_path.write_bytes(build_download_response.content)
        print(f"  Downloaded: {jar_path}")

    return jar_path


async def generate_dockerfile(build_directory, base_image_name, jar_path):
    print(f"  Creating... {build_directory}")

    build_directory_path = Path(build_directory)
    build_directory_path.mkdir(parents=True, exist_ok=True)

    DOCKERFILE_CONTENT = f"""FROM {base_image_name}
ADD {jar_path.relative_to(OUTPUT_DIRECTORY)} /
ENTRYPOINT ["{jar_path.name}"]"""

    dockerfile = build_directory_path.joinpath("Dockerfile")
    dockerfile.write(DOCKERFILE_CONTENT)

    print(f"  Created: {build_directory}")


async def build_docker_image(docker_client, docker_tag, dockerfile_path):
    image, logs = docker_client.build(
        dockerfile=dockerfile_path, tag=docker_tag, pull=True
    )
    return image


async def create_image(
    base_image_name,
    base_image_type,
    build,
    docker_client,
    project_name,
    session,
    version,
    version_url,
):
    build_download_url = f"{version_url}/{build}/download"

    build_directory = (
        f"{GENERATED_DIRECTORY}/{base_image_type}/{project_name}/{version}/{build}"
    )

    jar_path = await download_jar(
        project_name, version, build, build_download_url, session
    )

    dockerfile_path = await generate_dockerfile(
        build_directory, base_image_name, jar_path
    )

    docker_tag = f"{project_name}:{version}-{build}-{base_image_type}"
    await build_docker_image(docker_client, docker_tag, dockerfile_path)


async def main(docker_client, session):
    print("Starting...")

    all_create_image_coroutines = []

    for PROJECT_NAME in PROJECT_NAME_LIST:
        project_url = f"{HOST}api/{API_VERSION}/{PROJECT_NAME}"

        project_response = session.get(project_url)
        project_response_json = project_response.json()

        for version in project_response_json["versions"]:
            version_url = f"{project_url}/{version}"

            version_response = session.get(version_url)
            version_response_json = version_response.json()

            for (
                base_image_type,
                base_image_name,
            ) in BASE_DOCKER_IMAGE_DICTIONARY.items():
                all_builds = version_response_json["builds"]["all"]  # + ["latest"]

                create_image_coroutines = [
                    create_image(
                        base_image_name,
                        base_image_type,
                        build,
                        docker_client,
                        PROJECT_NAME,
                        session,
                        version,
                        version_url,
                    )
                    for build in all_builds
                ]

                all_create_image_coroutines = (
                    all_create_image_coroutines + create_image_coroutines
                )

    return asyncio.gather(*all_create_image_coroutines)
    # print("Finished!")


if __name__ == "__main__":
    assert sys.version_info >= (3, 7), "Script requires Python 3.7+."

    session = requests.Session()
    session.mount(HOST, HTTP20Adapter())

    docker_client = docker.from_env()

    event_loop = asyncio.get_event_loop()

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        event_loop.set_default_executor(pool)
        event_loop.run_until_complete(main(docker_client, session))
        # event_loop.run_in_executor(pool, main(docker_client, session))

    # event_loop.run_until_complete(main(docker_client, session))
    # asyncio.run(main(docker_client, session))
