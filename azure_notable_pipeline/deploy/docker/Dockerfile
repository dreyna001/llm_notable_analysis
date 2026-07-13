FROM mcr.microsoft.com/azure-functions/python:4-python3.12 AS dependencies

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --prefix=/opt/python \
    --requirement /tmp/requirements.txt

FROM mcr.microsoft.com/azure-functions/python:4-python3.12 AS runtime

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    ASPNETCORE_URLS=http://0.0.0.0:8080 \
    FUNCTIONS_WORKER_RUNTIME=python \
    PYTHONPATH=/home/site/wwwroot:/opt/python/lib/python3.12/site-packages \
    WEBSITES_PORT=8080

COPY --from=dependencies /opt/python /opt/python
COPY host.json function_app.py /home/site/wwwroot/
COPY src/azure_notable_pipeline /home/site/wwwroot/azure_notable_pipeline
COPY deploy/servicenow /home/site/wwwroot/deploy/servicenow

RUN useradd --create-home --uid 10001 functionsuser \
    && chown -R functionsuser:functionsuser /home/site/wwwroot /opt/python

USER 10001
EXPOSE 8080
