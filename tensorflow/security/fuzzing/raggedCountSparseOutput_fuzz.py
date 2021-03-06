# Copyright 2021 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""This is a Python API fuzzer for tf.raw_ops.RaggedCountSparseOutput."""
import atheris
with atheris.instrument_imports():
  import sys
  from python_fuzzing import FuzzingHelper
  import tensorflow as tf


@atheris.instrument_func
def TestOneInput(input_bytes):
  """Test randomized integer/float fuzzing input for tf.raw_ops.RaggedCountSparseOutput."""
  fh = FuzzingHelper(input_bytes)

  splits = fh.get_int_list()
  values = fh.get_int_or_float_list()
  weights = fh.get_int_list()
  try:
    _, _, _, = tf.raw_ops.RaggedCountSparseOutput(
        splits=splits, values=values, weights=weights, binary_output=False)
  except tf.errors.InvalidArgumentError:
    pass


def main():
  atheris.Setup(sys.argv, TestOneInput, enable_python_coverage=True)
  atheris.Fuzz()


if __name__ == "__main__":
  main()
