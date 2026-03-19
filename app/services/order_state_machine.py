class OrderStateMachine:
    # Valid transitions: {Current State: [Allowed Next States]}
    VALID_TRANSITIONS = {
        "NEW": ["PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED"],
        "PARTIALLY_FILLED": ["PARTIALLY_FILLED", "FILLED", "CANCELED"],
        "FILLED": [],    # Final state
        "CANCELED": [],  # Final state
        "REJECTED": []   # Final state
    }

    @classmethod
    def transition(cls, order, next_status):
        if next_status not in cls.VALID_TRANSITIONS.get(order.status, []):
            raise Exception(f"Invalid transition from {order.status} to {next_status}")
        
        order.status = next_status
        return order
