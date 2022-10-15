#!/bin/bash
redoc-cli build swagger.yml --template template.html
mv redoc-static.html static