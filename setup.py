from setuptools import setup, find_packages
import pathlib

HERE = pathlib.Path(__file__).parent

README = (HERE / "README.md").read_text(encoding="utf-8")

with open("requirements.txt") as f:
    REQUIREMENTS = f.read().splitlines()

VERSION = "0.1.1"

setup(
    name="freeweather",
    version=VERSION,
    author="Edoardo Federici",
    author_email="ohswedd@gmail.com",
    description="A Python library for fetching weather data using Open-Meteo API.",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/Ohswedd/freeweather",  
    packages=find_packages(exclude=["tests*"]),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",  
        "Operating System :: OS Independent",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries",
        "Topic :: Utilities",
    ],
    python_requires='>=3.7',
    install_requires=REQUIREMENTS,
    extras_require={
        "dev": [
            "pytest",
            "pytest-asyncio",
            "Faker",
            "black",
            "flake8",
        ],
    },
    include_package_data=True,  
    license="MIT", 
    keywords="weather open-meteo API",
)
