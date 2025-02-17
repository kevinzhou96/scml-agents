import functools
import math
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from negmas import (
    AgentMechanismInterface,
    AspirationNegotiator,
    Issue,
    Negotiator,
    SAONegotiator,
)
from negmas.helpers import get_class
from scml import TIME, NegotiationManager
from scml.scml2020.components.negotiation import ControllerInfo
from scml.scml2020.services import StepController

from .ModifiedERPStrategy import ModifiedERPStrategy


class ModifiedStepNegotiationManager(ModifiedERPStrategy, NegotiationManager):
    def __init__(
        self,
        *args,
        negotiator_type: Union[SAONegotiator, str] = AspirationNegotiator,
        negotiator_params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        # save construction parameters
        self.negotiator_type = get_class(negotiator_type)
        self.negotiator_params = (
            negotiator_params if negotiator_params is not None else dict()
        )

        self.buyers = self.sellers = None

    def init(self):
        super().init()

        # initialize one controller for buying and another for selling for each time-step
        self.buyers: List[ControllerInfo] = [
            ControllerInfo(None, i, False, tuple(), 0, 0, False)
            for i in range(self.awi.n_steps)
        ]
        self.sellers: List[ControllerInfo] = [
            ControllerInfo(None, i, True, tuple(), 0, 0, False)
            for i in range(self.awi.n_steps)
        ]

    def _start_negotiations(
        self,
        product: int,
        sell: bool,
        step: int,
        qvalues: Tuple[int, int],
        uvalues: Tuple[int, int],
        tvalues: Tuple[int, int],
        partners: List[str],
    ) -> None:

        execution_fraction = np.array(
            [
                self._execution_fractions[partner]
                if partner in self._execution_fractions
                else self._default_execution_fraction
                for partner in partners
            ]
        ).mean()

        expected_quantity = int(math.floor(qvalues[1] * execution_fraction))

        controller = self.create_controller(
            sell, qvalues[1], uvalues, expected_quantity, step
        )

        if self.awi.request_negotiations(
            is_buy=not sell,
            product=product,
            quantity=qvalues,
            unit_price=uvalues,
            time=tvalues,
            partners=partners,
            controller=controller,
            extra=dict(controller_index=step, is_seller=sell),
        ):
            self.add_controller(
                controller, sell, qvalues[1], uvalues, expected_quantity, step
            )

    def respond_to_negotiation_request(
        self,
        initiator: str,
        issues: List[Issue],
        annotation: Dict[str, Any],
        mechanism: AgentMechanismInterface,
    ) -> Optional[Negotiator]:

        # find negotiation parameters
        is_seller = annotation["seller"] == self.id
        t_min, t_max = issues[TIME].min_value, issues[TIME].max_value + 1
        # find the time-step for which this negotiation should be added
        step = max(0, t_min - 1) if is_seller else min(self.awi.n_steps - 1, t_max + 1)
        # find the corresponding controller.
        controller_info: ControllerInfo
        controller_info = self.sellers[step] if is_seller else self.buyers[step]

        target = self.target_quantities((t_min, t_max + 1), is_seller).sum()
        if target <= 0:
            return None

        if controller_info.controller is None:
            controller = self.create_controller(
                is_seller,
                target,
                self._urange(step, is_seller, (t_min, t_max)),
                int(target),
                step,
            )
            controller = self.add_controller(
                controller,
                is_seller,
                target,
                self._urange(step, is_seller, (t_min, t_max)),
                int(target),
                step,
            )
        else:
            controller = controller_info.controller

        # create a new negotiator, add it to the controller and return it
        return controller.create_negotiator(id=initiator)

    def all_negotiations_concluded(
        self, controller_index: int, is_seller: bool
    ) -> None:
        """Called by the `StepController` to affirm that it is done negotiating for some time-step"""
        info = (
            self.sellers[controller_index]
            if is_seller
            else self.buyers[controller_index]
        )
        info.done = True
        c = info.controller
        if c is None:
            return
        quantity = c.secured
        target = c.target
        if is_seller:
            controllers = self.sellers
        else:
            controllers = self.buyers

        controllers[controller_index].controller = None
        if quantity <= target:
            self._generate_negotiations(step=controller_index, sell=is_seller)
            return

    def add_controller(
        self,
        controller: StepController,
        is_seller: bool,
        target,
        urange: Tuple[int, int],
        expected_quantity: int,
        step: int,
    ) -> StepController:
        if is_seller:
            # assert self.sellers[step].controller is None
            self.sellers[step] = ControllerInfo(
                controller,
                step,
                is_seller,
                self._trange(step, is_seller),
                target,
                expected_quantity,
                False,
            )
        else:
            # assert self.buyers[step].controller is None
            self.buyers[step] = ControllerInfo(
                controller,
                step,
                is_seller,
                self._trange(step, is_seller),
                target,
                expected_quantity,
                False,
            )
        return controller

    def create_controller(
        self,
        is_seller: bool,
        target,
        urange: Tuple[int, int],
        expected_quantity: int,
        step: int,
    ) -> StepController:
        if is_seller and self.sellers[step].controller is not None:
            return self.sellers[step].controller
        if not is_seller and self.buyers[step].controller is not None:
            return self.buyers[step].controller
        return StepController(
            is_seller=is_seller,
            target_quantity=target * 1.2
            if target < expected_quantity
            else target * 0.8,
            negotiator_type=self.negotiator_type,
            negotiator_params=self.negotiator_params,
            step=step,
            urange=urange,
            product=self.awi.my_output_product
            if is_seller
            else self.awi.my_input_product,
            partners=self.awi.my_consumers if is_seller else self.awi.my_suppliers,
            horizon=self._horizon,
            negotiations_concluded_callback=functools.partial(
                self.__class__.all_negotiations_concluded, self
            ),
            parent_name=self.name,
            awi=self.awi,
        )

    def _get_controller(self, mechanism) -> StepController:
        neg = self._running_negotiations[mechanism.id]
        return neg.negotiator.parent
