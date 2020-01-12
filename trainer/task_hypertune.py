"""Manage the training job, with hyperparameters tuning enabled."""

from .model import build_model
from google.cloud import storage
from tensorflow.core.framework.summary_pb2 import Summary
from tensorflow.keras import losses
from tensorflow.keras import metrics
from tensorflow.keras import optimizers
from tensorflow.keras.datasets import mnist
from tensorflow.keras.utils import to_categorical

import argparse
import logging.config
import os
import tensorflow as tf
import time

LOGGER = logging.getLogger()


def prepare_data():
  """Download and preprocess data for the model.

  Returns:
   A tuple of train and test data.
   Each one of those elements is also a tuple of (x,y)

  """
  LOGGER.info("Preparing and downloading data")

  train_data, test_data = mnist.load_data()

  x_train, y_train = train_data
  x_test, y_test = test_data

  x_train_norm = _preprocess_x(x_train)
  x_test_norm = _preprocess_x(x_test)

  y_train_cat = _preprocess_y(y_train)
  y_test_cat = _preprocess_y(y_test)

  train_data_prep = (x_train_norm, y_train_cat)
  test_data_prep = (x_test_norm, y_test_cat)

  return train_data_prep, test_data_prep


def train_and_evaluate(train_data,
                       test_data,
                       bucket_name,
                       path_in_bucket,
                       job_dir,
                       batch_size,
                       epochs):
  """Train and evaluate the model, and serialize to output dir."""
  # Callback for logs inpsection with Tensorboard
  logdir = os.path.join(job_dir,
                        "logs/scalars/" + time.strftime("%Y%m%d-%H%M%S"))
  LOGGER.info("Writing TensorBoard logs to %s" % logdir)
  tb_callback = tf.keras.callbacks.TensorBoard(log_dir=logdir)

  m = build_model()
  m.compile(optimizer=optimizers.Adam(),
            loss=losses.categorical_crossentropy,
            metrics=[metrics.categorical_accuracy])

  x_train, y_train = train_data
  x_test, y_test = test_data

  m.fit(x_train,
        y_train,
        batch_size=batch_size,
        epochs=epochs,
        callbacks=[tb_callback])
  test_loss, test_acc = m.evaluate(x_test, y_test)

  localfn = 'mymodel.h5'
  m.save(localfn)

  # Upload to GCS
  fn = 'mnist_keras_' + time.strftime("%Y%m%d%H%M%S") + '.h5'
  output_path_gcs = os.path.join(path_in_bucket, fn)
  client = storage.Client()
  bucket = client.bucket(bucket_name)
  blob = bucket.blob(output_path_gcs)
  LOGGER.info("Uploading model to %s" % output_path_gcs)
  blob.upload_from_filename(localfn)

  # Report metrics to Cloud ML Engine for hypertuning
  metric_tag = 'accuracyMnist'
  summary = Summary(value=[Summary.Value(tag=metric_tag,
                                         simple_value=test_acc)])
  eval_path = os.path.join(job_dir, metric_tag)
  LOGGER.info("Writing metrics to %s" % eval_path)
  summary_writer = tf.summary.FileWriter(eval_path)

  summary_writer.add_summary(summary)
  summary_writer.flush()


def _preprocess_x(x):
  return x / 255.0


def _preprocess_y(y):
  return to_categorical(y)


if '__main__' == __name__:
  parser = argparse.ArgumentParser()
  parser.add_argument(
      '--output-bucket',
      required=True,
      help='Output GCS bucket (withot the gs:// prefix)'
      'to write the serialized trained model')
  parser.add_argument(
      '--output-path',
      default='',
      required=True,
      help='Relative path in the bucket for '
      'to write the serialized trained model')
  parser.add_argument(
      '--batch-size',
      type=int,
      default=64,
      help='Batch size for training and evaluation.')
  parser.add_argument(
      '--epochs',
      type=int,
      default=30,
      help='Number of steps to train the model')
  parser.add_argument(
      '--job-dir',
      default=None,
      required=False,
      help='Job dir for Cloud ML Engine')

  args = parser.parse_args()

  bucket_name = args.output_bucket
  output_path = args.output_path
  batch_size = args.batch_size
  epochs = args.epochs
  job_dir = args.job_dir

  train_data, test_data = prepare_data()
  train_and_evaluate(train_data,
                     test_data,
                     bucket_name,
                     output_path,
                     job_dir,
                     batch_size,
                     epochs)
