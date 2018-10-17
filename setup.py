#!/usr/bin/env python
from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="target-snowflake",
    version="0.1.0",
    author="Meltano",
    author_email="meltano@gitlab.com",
    description="Singer.io target for importing data to Snowflake",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://gitlab.com/meltano/target-snowflake",
    classifiers=["Programming Language :: Python :: 3 :: Only"],
    install_requires=[
        'inflection>=0.3.1',
        'singer-python>=5.0.12',
        'snowflake-connector-python',
        'snowflake-sqlalchemy>=1.1.2',
    ],
    extras_require={
        'dev': [
            'pytest>=3.8',
            'black>=18.3a0',
        ]
    },
    entry_points="""
    [console_scripts]
    target-snowflake=target_snowflake:main
    """,
    python_requires='>=3.6',
    packages=find_packages(exclude=['tests']),
    package_data = {},
    include_package_data=True,
)