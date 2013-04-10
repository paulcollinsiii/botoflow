# Copyright 2013 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#  http://aws.amazon.com/apache2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

import six


class _WorkflowDefinitionMeta(type):
    def __init__(cls, name, bases, dct):
        # find the workflows/signals and add them to our class
        _workflow_types = []
        signals = {}

        for val in six.itervalues(dct):
            if hasattr(val, 'func'):
                func = val.func
                if hasattr(func, 'swf_options'):
                    if 'signal_type' in func.swf_options:
                        signal_type = func.swf_options['signal_type']
                        signals[signal_type.name] = func
                    elif 'workflow_type' in func.swf_options:
                        _workflow_types.append((
                            func.swf_options['workflow_type'], func.__name__))

        super(_WorkflowDefinitionMeta, cls).__init__(name, bases, dct)
        # this is important, we don't want to spoil the base class with
        # attributes as otherwise they would propagate to subclasses
        if cls.__name__ == 'WorkflowDefinition':
            return

        if not hasattr(cls, '_workflow_signals'):
            setattr(cls, '_workflow_signals', signals)
        else:
            cls._workflow_signals.update(signals)

        workflow_types = {}
        for workflow_type, func_name in _workflow_types:
            workflow_type._reset_name(cls.__name__)
            workflow_types[workflow_type] = func_name

        if not hasattr(cls, '_workflow_types'):
            setattr(cls, '_workflow_types', workflow_types)
        else:
            cls._workflow_types.update(workflow_types)

        # XXX need to rethink this: a base might, or might not have @execute,
        # so somehow we need to apply this only to the leafmost class
        # if len(cls._workflow_types) < 1:
        #     raise TypeError("WorkflowDefinition must have at least one "
        #                     "method decorated with @execute")


class WorkflowDefinition(object):
    """Every workflow implementation needs to be a subclass of this class.

    Usually there should be no need to instantiate the class manually, as
    instead, the @execute method is called to start the workflow (you can think
    of ths as having factory class methods).

    Here's an example workflow implementation that has an @execute decorated
    method and a @signal:

    .. code-block:: python

        from awsflow import execute, Return, WorkflowDefinition
        from awsflow.constants import MINUTES

        from my_activities import MyActivities


        class MyWorkflow(WorkflowDefinition):

            @execute(version='1.0', execution_start_to_close_timeout=1*MINUTES)
            def start_my_workflow(self, some_input):
                # execute the activity and wait for it's result
                result = yield MyActivities.activity1(some_input)

                # return the result from the workflow
                raise Return(result)

            @signal()  # has to have () parentheses
            def signal1(self, signal_input):
                self.signal_input = signal_input

    As with the @async decorated methods, returning values from the workflow is
    a little bit inconvenient on Python 2 as instead of using the familiar
    return keyword, the return value is "raised" like this: `raise
    Return("Value")`.
    """

    __metaclass__ = _WorkflowDefinitionMeta

    def __init__(self, workflow_execution):
        self.workflow_execution = workflow_execution
        self.workflow_state = ""
        self._workflow_result = None

    @property
    def workflow_execution(self):
        """Will contain the
        :py:class:`awsflow.workflow_execution.WorkflowExecution` named tuple
        of the currently running workflow.

        An example of the workflow_execution after starting a workflow:

        .. code-block:: python

            # create the workflow using boto swf_client and ExampleWorkflow class
            wf_worker = WorkflowWorker(swf_client, "SOMEDOMAIN", "MYTASKLIST"
                                       ExampleWorkflow)

            # start the workflow with a random workflow_id
            with wf_worker:
                instance = OneActivityWorkflow.execute(arg1=1, arg2=2)
                print instance.workflow_execution
                # prints:
                # WorkflowExecution(
                #      workflow_id='73faf493fece67fefb1142739611c391a03bc23b',
                #      run_id='12Eg0ETHpm17rSWssUZKqAvEZVd5Ap0RELs8kE7U6igB8=')

        """
        return self.__workflow_execution

    @workflow_execution.setter
    def workflow_execution(self, workflow_execution):
        self.__workflow_execution = workflow_execution

    @property
    def workflow_state(self):
        """This property is used to retrieve current workflow state.
        The property is expected to perform read only access of the workflow
        implementation object and is invoked synchronously which disallows
        use of any asynchronous operations (like calling it with `yield`).

        The latest state reported by the workflow execution is returned to
        you through visibility calls to the Amazon SWF service and in the
        Amazon SWF console.

        Example of setting the state between `yield` s:

        .. code-block:: python

            class MyWorkflow(WorkflowDefinition):

                @execute(version='1.0', execution_start_to_close_timeout=1*MINUTES)
                def start_workflow(self):
                    self.workflow_state = "Workflow started"
                    yield SomeActivity.method(1, 2)
                    self.workflow_state = "Workflow completing"
        """
        return self.__workflow_state

    @workflow_state.setter
    def workflow_state(self, state):
        self.__workflow_state = state

    @property
    def workflow_result(self):
        """This property returns the future associated with the result of the
        workflow execution.

        The main use-case is when you have subworkflows, which results you'd
        like to `yield` on and still be able to call signals on that
        sub-workflow.

        :returns: `awsflow.core.future.Future`, or None if the workflow has
            not been started.
        """
        return self._workflow_result