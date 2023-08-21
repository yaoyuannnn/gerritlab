#!/usr/bin/env python

from setuptools import setup

setup(name='gerritlab',
      version='1.0.0',
      description='Gerrit-like code review for GitLab',
      author='Yuan Yao',
      author_email='yaoyuannnn@gmail.com',
      url='https://github.com/yaoyuannnn/gerritlab',
      packages=['gerritlab'],
      package_data={"gerritlab": ["commit-msg"]},
      entry_points={
          'console_scripts': ['git-lab = gerritlab.main:main'],
      },
      install_requires=[line.strip() for line in open("requirements.txt")],
     )
