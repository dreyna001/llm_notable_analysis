# Use AWS Lambda Python 3.12 base image
FROM public.ecr.aws/lambda/python:3.12

# Copy requirements file
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install Python dependencies
# Note: boto3 is already included in the Lambda base image
RUN pip install --no-cache-dir -r requirements.txt

# Copy function code and data files
COPY lambda_handler.py ${LAMBDA_TASK_ROOT}
COPY ttp_analyzer.py ${LAMBDA_TASK_ROOT}
COPY markdown_generator.py ${LAMBDA_TASK_ROOT}
COPY enterprise_attack_v17.1_ids.json ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler (could also be done as a parameter override)
CMD ["lambda_handler.handler"]

