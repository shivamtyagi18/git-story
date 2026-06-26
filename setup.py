from setuptools import setup, find_packages

setup(
    name="git-story",
    version="0.1.0",
    author="Antigravity",
    description="Interactive Git History & Architecture Evolution Generator",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "requests>=2.25.0",
        "jinja2>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "git-story=git_story.cli:main",
        ],
    },
    python_requires=">=3.7",
)
