# Copyright 2018 The TensorFlow Authors. All Rights Reserved.
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
"""Tests for `tf.data.Optional`."""
import functools

from absl.testing import parameterized
import numpy as np

from tensorflow.python.data.kernel_tests import test_base
from tensorflow.python.data.ops import dataset_ops
from tensorflow.python.data.ops import iterator_ops
from tensorflow.python.data.ops import optional_ops
from tensorflow.python.data.util import structure
from tensorflow.python.eager import context
from tensorflow.python.eager import def_function
from tensorflow.python.framework import combinations
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import errors
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor
from tensorflow.python.framework import tensor_shape
from tensorflow.python.framework import tensor_spec
from tensorflow.python.framework import test_util
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.platform import test


def _optional_spec_test_combinations():
  # pylint: disable=g-long-lambda
  cases = [
      ("Dense", lambda: constant_op.constant(37.0),
       tensor_spec.TensorSpec([], dtypes.float32)),
      ("Sparse", lambda: sparse_tensor.SparseTensor(
          indices=[[0, 1]],
          values=constant_op.constant([0], dtype=dtypes.int32),
          dense_shape=[10, 10]),
       sparse_tensor.SparseTensorSpec([10, 10], dtypes.int32)),
      ("Nest", lambda: {
          "a": constant_op.constant(37.0),
          "b": (constant_op.constant(["Foo"]), constant_op.constant("Bar"))
      }, {
          "a":
              tensor_spec.TensorSpec([], dtypes.float32),
          "b": (
              tensor_spec.TensorSpec([1], dtypes.string),
              tensor_spec.TensorSpec([], dtypes.string),
          )
      }),
      ("Optional", lambda: optional_ops.Optional.from_value(37.0),
       optional_ops.OptionalSpec(tensor_spec.TensorSpec([], dtypes.float32))),
  ]

  def reduce_fn(x, y):
    name, value_fn, expected_structure = y
    return x + combinations.combine(
        tf_value_fn=combinations.NamedObject(name, value_fn),
        expected_value_structure=expected_structure)

  return functools.reduce(reduce_fn, cases, [])


def _get_next_as_optional_test_combinations():
  # pylint: disable=g-long-lambda
  cases = [
      ("Dense", np.array([1, 2, 3], dtype=np.int32),
       lambda: constant_op.constant([4, 5, 6], dtype=dtypes.int32), True),
      ("Sparse",
       sparse_tensor.SparseTensorValue(
           indices=[[0, 0], [1, 1]],
           values=np.array([-1., 1.], dtype=np.float32),
           dense_shape=[2, 2]),
       lambda: sparse_tensor.SparseTensor(
           indices=[[0, 1], [1, 0]], values=[37.0, 42.0], dense_shape=[2, 2]),
       False),
      ("Nest", {
          "a":
              np.array([1, 2, 3], dtype=np.int32),
          "b":
              sparse_tensor.SparseTensorValue(
                  indices=[[0, 0], [1, 1]],
                  values=np.array([-1., 1.], dtype=np.float32),
                  dense_shape=[2, 2])
      }, lambda: {
          "a":
              constant_op.constant([4, 5, 6], dtype=dtypes.int32),
          "b":
              sparse_tensor.SparseTensor(
                  indices=[[0, 1], [1, 0]],
                  values=[37.0, 42.0],
                  dense_shape=[2, 2])
      }, False),
  ]

  def reduce_fn(x, y):
    name, value, value_fn, gpu_compatible = y
    return x + combinations.combine(
        np_value=value,
        tf_value_fn=combinations.NamedObject(name, value_fn),
        gpu_compatible=gpu_compatible)

  return functools.reduce(reduce_fn, cases, [])


class OptionalTest(test_base.DatasetTestBase, parameterized.TestCase):

  @combinations.generate(test_base.default_test_combinations())
  def testFromValue(self):
    opt = optional_ops.Optional.from_value(constant_op.constant(37.0))
    self.assertTrue(self.evaluate(opt.has_value()))
    self.assertEqual(37.0, self.evaluate(opt.get_value()))

  @combinations.generate(test_base.default_test_combinations())
  def testFromStructuredValue(self):
    opt = optional_ops.Optional.from_value({
        "a": constant_op.constant(37.0),
        "b": (constant_op.constant(["Foo"]), constant_op.constant("Bar"))
    })
    self.assertTrue(self.evaluate(opt.has_value()))
    self.assertEqual({
        "a": 37.0,
        "b": ([b"Foo"], b"Bar")
    }, self.evaluate(opt.get_value()))

  @combinations.generate(test_base.default_test_combinations())
  def testFromSparseTensor(self):
    st_0 = sparse_tensor.SparseTensorValue(
        indices=np.array([[0]]),
        values=np.array([0], dtype=np.int64),
        dense_shape=np.array([1]))
    st_1 = sparse_tensor.SparseTensorValue(
        indices=np.array([[0, 0], [1, 1]]),
        values=np.array([-1., 1.], dtype=np.float32),
        dense_shape=np.array([2, 2]))
    opt = optional_ops.Optional.from_value((st_0, st_1))
    self.assertTrue(self.evaluate(opt.has_value()))
    val_0, val_1 = opt.get_value()
    for expected, actual in [(st_0, val_0), (st_1, val_1)]:
      self.assertAllEqual(expected.indices, self.evaluate(actual.indices))
      self.assertAllEqual(expected.values, self.evaluate(actual.values))
      self.assertAllEqual(expected.dense_shape,
                          self.evaluate(actual.dense_shape))

  @combinations.generate(test_base.default_test_combinations())
  def testFromNone(self):
    value_structure = tensor_spec.TensorSpec([], dtypes.float32)
    opt = optional_ops.Optional.empty(value_structure)
    self.assertTrue(opt.element_spec.is_compatible_with(value_structure))
    self.assertFalse(
        opt.element_spec.is_compatible_with(
            tensor_spec.TensorSpec([1], dtypes.float32)))
    self.assertFalse(
        opt.element_spec.is_compatible_with(
            tensor_spec.TensorSpec([], dtypes.int32)))
    self.assertFalse(self.evaluate(opt.has_value()))
    with self.assertRaises(errors.InvalidArgumentError):
      self.evaluate(opt.get_value())

  @combinations.generate(test_base.default_test_combinations())
  def testAddN(self):
    devices = ["/cpu:0"]
    if test_util.is_gpu_available():
      devices.append("/gpu:0")
    for device in devices:
      with ops.device(device):
        # With value
        opt1 = optional_ops.Optional.from_value((1.0, 2.0))
        opt2 = optional_ops.Optional.from_value((3.0, 4.0))

        add_tensor = math_ops.add_n(
            [opt1._variant_tensor, opt2._variant_tensor])
        add_opt = optional_ops._OptionalImpl(add_tensor, opt1.element_spec)
        self.assertAllEqual(self.evaluate(add_opt.get_value()), (4.0, 6.0))

        # Without value
        opt_none1 = optional_ops.Optional.empty(opt1.element_spec)
        opt_none2 = optional_ops.Optional.empty(opt2.element_spec)
        add_tensor = math_ops.add_n(
            [opt_none1._variant_tensor, opt_none2._variant_tensor])
        add_opt = optional_ops._OptionalImpl(add_tensor, opt_none1.element_spec)
        self.assertFalse(self.evaluate(add_opt.has_value()))

  @combinations.generate(test_base.default_test_combinations())
  def testNestedAddN(self):
    devices = ["/cpu:0"]
    if test_util.is_gpu_available():
      devices.append("/gpu:0")
    for device in devices:
      with ops.device(device):
        opt1 = optional_ops.Optional.from_value([1, 2.0])
        opt2 = optional_ops.Optional.from_value([3, 4.0])
        opt3 = optional_ops.Optional.from_value((5.0, opt1._variant_tensor))
        opt4 = optional_ops.Optional.from_value((6.0, opt2._variant_tensor))

        add_tensor = math_ops.add_n(
            [opt3._variant_tensor, opt4._variant_tensor])
        add_opt = optional_ops._OptionalImpl(add_tensor, opt3.element_spec)
        self.assertEqual(self.evaluate(add_opt.get_value()[0]), 11.0)

        inner_add_opt = optional_ops._OptionalImpl(add_opt.get_value()[1],
                                                   opt1.element_spec)
        self.assertAllEqual(inner_add_opt.get_value(), [4, 6.0])

  @combinations.generate(test_base.default_test_combinations())
  def testZerosLike(self):
    devices = ["/cpu:0"]
    if test_util.is_gpu_available():
      devices.append("/gpu:0")
    for device in devices:
      with ops.device(device):
        # With value
        opt = optional_ops.Optional.from_value((1.0, 2.0))
        zeros_tensor = array_ops.zeros_like(opt._variant_tensor)
        zeros_opt = optional_ops._OptionalImpl(zeros_tensor, opt.element_spec)
        self.assertAllEqual(self.evaluate(zeros_opt.get_value()), (0.0, 0.0))

        # Without value
        opt_none = optional_ops.Optional.empty(opt.element_spec)
        zeros_tensor = array_ops.zeros_like(opt_none._variant_tensor)
        zeros_opt = optional_ops._OptionalImpl(zeros_tensor,
                                               opt_none.element_spec)
        self.assertFalse(self.evaluate(zeros_opt.has_value()))

  @combinations.generate(test_base.default_test_combinations())
  def testNestedZerosLike(self):
    devices = ["/cpu:0"]
    if test_util.is_gpu_available():
      devices.append("/gpu:0")
    for device in devices:
      with ops.device(device):
        opt1 = optional_ops.Optional.from_value(1.0)
        opt2 = optional_ops.Optional.from_value(opt1._variant_tensor)

        zeros_tensor = array_ops.zeros_like(opt2._variant_tensor)
        zeros_opt = optional_ops._OptionalImpl(zeros_tensor, opt2.element_spec)
        inner_zeros_opt = optional_ops._OptionalImpl(zeros_opt.get_value(),
                                                     opt1.element_spec)
        self.assertEqual(self.evaluate(inner_zeros_opt.get_value()), 0.0)

  @combinations.generate(test_base.default_test_combinations())
  def testCopyToGPU(self):
    if not test_util.is_gpu_available():
      self.skipTest("No GPU available")

    with ops.device("/cpu:0"):
      optional_with_value = optional_ops.Optional.from_value(
          (constant_op.constant(37.0), constant_op.constant("Foo"),
           constant_op.constant(42)))
      optional_none = optional_ops.Optional.empty(
          tensor_spec.TensorSpec([], dtypes.float32))

    with ops.device("/gpu:0"):
      gpu_optional_with_value = optional_ops._OptionalImpl(
          array_ops.identity(optional_with_value._variant_tensor),
          optional_with_value.element_spec)
      gpu_optional_none = optional_ops._OptionalImpl(
          array_ops.identity(optional_none._variant_tensor),
          optional_none.element_spec)

      gpu_optional_with_value_has_value = gpu_optional_with_value.has_value()
      gpu_optional_with_value_values = gpu_optional_with_value.get_value()

      gpu_optional_none_has_value = gpu_optional_none.has_value()

    self.assertTrue(self.evaluate(gpu_optional_with_value_has_value))
    self.assertEqual((37.0, b"Foo", 42),
                     self.evaluate(gpu_optional_with_value_values))
    self.assertFalse(self.evaluate(gpu_optional_none_has_value))

  @combinations.generate(test_base.default_test_combinations())
  def testNestedCopyToGPU(self):
    if not test_util.is_gpu_available():
      self.skipTest("No GPU available")

    with ops.device("/cpu:0"):
      optional_with_value = optional_ops.Optional.from_value(
          (constant_op.constant(37.0), constant_op.constant("Foo"),
           constant_op.constant(42)))
      optional_none = optional_ops.Optional.empty(
          tensor_spec.TensorSpec([], dtypes.float32))
      nested_optional = optional_ops.Optional.from_value(
          (optional_with_value._variant_tensor, optional_none._variant_tensor,
           1.0))

    with ops.device("/gpu:0"):
      gpu_nested_optional = optional_ops._OptionalImpl(
          array_ops.identity(nested_optional._variant_tensor),
          nested_optional.element_spec)

      gpu_nested_optional_has_value = gpu_nested_optional.has_value()
      gpu_nested_optional_values = gpu_nested_optional.get_value()

    self.assertTrue(self.evaluate(gpu_nested_optional_has_value))

    inner_with_value = optional_ops._OptionalImpl(
        gpu_nested_optional_values[0], optional_with_value.element_spec)

    inner_none = optional_ops._OptionalImpl(gpu_nested_optional_values[1],
                                            optional_none.element_spec)

    self.assertEqual((37.0, b"Foo", 42),
                     self.evaluate(inner_with_value.get_value()))
    self.assertFalse(self.evaluate(inner_none.has_value()))
    self.assertEqual(1.0, self.evaluate(gpu_nested_optional_values[2]))

  @combinations.generate(
      combinations.times(test_base.default_test_combinations(),
                         _optional_spec_test_combinations()))
  def testOptionalSpec(self, tf_value_fn, expected_value_structure):
    tf_value = tf_value_fn()
    opt = optional_ops.Optional.from_value(tf_value)

    self.assertTrue(
        structure.are_compatible(opt.element_spec, expected_value_structure))

    opt_structure = structure.type_spec_from_value(opt)
    self.assertIsInstance(opt_structure, optional_ops.OptionalSpec)
    self.assertTrue(structure.are_compatible(opt_structure, opt_structure))
    self.assertTrue(
        structure.are_compatible(opt_structure._element_spec,
                                 expected_value_structure))
    self.assertEqual([dtypes.variant],
                     structure.get_flat_tensor_types(opt_structure))
    self.assertEqual([tensor_shape.TensorShape([])],
                     structure.get_flat_tensor_shapes(opt_structure))

    # All OptionalSpec objects are not compatible with a non-optional
    # value.
    non_optional_structure = structure.type_spec_from_value(
        constant_op.constant(42.0))
    self.assertFalse(opt_structure.is_compatible_with(non_optional_structure))

    # Assert that the optional survives a round-trip via _from_tensor_list()
    # and _to_tensor_list().
    round_trip_opt = opt_structure._from_tensor_list(
        opt_structure._to_tensor_list(opt))
    if isinstance(tf_value, optional_ops.Optional):
      self.assertValuesEqual(
          self.evaluate(tf_value.get_value()),
          self.evaluate(round_trip_opt.get_value().get_value()))
    else:
      self.assertValuesEqual(
          self.evaluate(tf_value), self.evaluate(round_trip_opt.get_value()))

  @combinations.generate(
      combinations.times(test_base.default_test_combinations(),
                         _get_next_as_optional_test_combinations()))
  def testIteratorGetNextAsOptional(self, np_value, tf_value_fn,
                                    gpu_compatible):
    if not gpu_compatible and test.is_gpu_available():
      self.skipTest("Test case not yet supported on GPU.")
    ds = dataset_ops.Dataset.from_tensors(np_value).repeat(3)

    if context.executing_eagerly():
      iterator = dataset_ops.make_one_shot_iterator(ds)
      # For each element of the dataset, assert that the optional evaluates to
      # the expected value.
      for _ in range(3):
        next_elem = iterator_ops.get_next_as_optional(iterator)
        self.assertIsInstance(next_elem, optional_ops.Optional)
        self.assertTrue(
            structure.are_compatible(
                next_elem.element_spec,
                structure.type_spec_from_value(tf_value_fn())))
        self.assertTrue(next_elem.has_value())
        self.assertValuesEqual(np_value, next_elem.get_value())
      # After exhausting the iterator, `next_elem.has_value()` will evaluate to
      # false, and attempting to get the value will fail.
      for _ in range(2):
        next_elem = iterator_ops.get_next_as_optional(iterator)
        self.assertFalse(self.evaluate(next_elem.has_value()))
        with self.assertRaises(errors.InvalidArgumentError):
          self.evaluate(next_elem.get_value())
    else:
      iterator = dataset_ops.make_initializable_iterator(ds)
      next_elem = iterator_ops.get_next_as_optional(iterator)
      self.assertIsInstance(next_elem, optional_ops.Optional)
      self.assertTrue(
          structure.are_compatible(
              next_elem.element_spec,
              structure.type_spec_from_value(tf_value_fn())))
      # Before initializing the iterator, evaluating the optional fails with
      # a FailedPreconditionError. This is only relevant in graph mode.
      elem_has_value_t = next_elem.has_value()
      elem_value_t = next_elem.get_value()
      with self.assertRaises(errors.FailedPreconditionError):
        self.evaluate(elem_has_value_t)
      with self.assertRaises(errors.FailedPreconditionError):
        self.evaluate(elem_value_t)
      # Now we initialize the iterator.
      self.evaluate(iterator.initializer)
      # For each element of the dataset, assert that the optional evaluates to
      # the expected value.
      for _ in range(3):
        elem_has_value, elem_value = self.evaluate(
            [elem_has_value_t, elem_value_t])
        self.assertTrue(elem_has_value)
        self.assertValuesEqual(np_value, elem_value)

      # After exhausting the iterator, `next_elem.has_value()` will evaluate to
      # false, and attempting to get the value will fail.
      for _ in range(2):
        self.assertFalse(self.evaluate(elem_has_value_t))
        with self.assertRaises(errors.InvalidArgumentError):
          self.evaluate(elem_value_t)

  @combinations.generate(test_base.default_test_combinations())
  def testFunctionBoundaries(self):

    @def_function.function
    def get_optional():
      x = constant_op.constant(1.0)
      opt = optional_ops.Optional.from_value(x)
      # TODO(skyewm): support returning Optionals from functions?
      return opt._variant_tensor

    # TODO(skyewm): support Optional arguments?
    @def_function.function
    def consume_optional(opt_tensor):
      value_structure = tensor_spec.TensorSpec([], dtypes.float32)
      opt = optional_ops._OptionalImpl(opt_tensor, value_structure)
      return opt.get_value()

    opt_tensor = get_optional()
    val = consume_optional(opt_tensor)
    self.assertEqual(self.evaluate(val), 1.0)

  @combinations.generate(test_base.default_test_combinations())
  def testLimitedRetracing(self):
    trace_count = [0]

    @def_function.function
    def f(opt):
      trace_count[0] += 1
      return opt.get_value()

    opt1 = optional_ops.Optional.from_value(constant_op.constant(37.0))
    opt2 = optional_ops.Optional.from_value(constant_op.constant(42.0))

    for _ in range(10):
      self.assertEqual(self.evaluate(f(opt1)), 37.0)
      self.assertEqual(self.evaluate(f(opt2)), 42.0)
      self.assertEqual(trace_count[0], 1)


if __name__ == "__main__":
  test.main()
