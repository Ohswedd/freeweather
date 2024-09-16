from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="freeweather",  # Replace with your desired package name
    version="0.1.0",
    author="Edoardo Federici",
    author_email="ohswedd@gmail.com",
    description="A Python library for fetching weather data using Open-Meteo API.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ohswedd/freeweather", 
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License", 
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
    install_requires=[
        "httpx",
        "pydantic",
        "pytest",
        "pytest-asyncio",
        "anyio",
        "Faker",
        "tenacity",
    ],
    extras_require={
        "dev": [
            "pytest",
            "pytest-asyncio",
            "Faker",
        ],
    },
    include_package_data=True,
    package_data={
        # If you have non-Python files, specify them here
    },
)
