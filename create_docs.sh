#!/bin/bash
redoc-cli build -t template.html swagger.yml
mv redoc-static.html static