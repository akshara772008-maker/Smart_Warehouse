import socket


HOST = "127.0.0.1"
PORT = 5001
MAX_REQUEST_BYTES = 4096


def send_order(order):
    if not isinstance(order, str) or not order.strip():
        print("Order must be a non-empty string")
        return False

    try:
        encoded_order = order.strip().encode("utf-8")
        if len(encoded_order) > MAX_REQUEST_BYTES:
            print(
                "Order must not exceed "
                f"{MAX_REQUEST_BYTES} UTF-8 bytes"
            )
            return False

        with socket.create_connection((HOST, PORT), timeout=5) as client:
            client.settimeout(5)
            client.sendall(encoded_order + b"\n")
            client.shutdown(socket.SHUT_WR)

            response = bytearray()
            while True:
                chunk = client.recv(1024)
                if not chunk:
                    break
                response.extend(chunk)

        print("======================================")
        print("SMART WAREHOUSE TCP CLIENT")
        print("======================================")
        print("Sent:", order.strip())
        print("Server response:", response.decode("utf-8"))
        return True
    except (OSError, UnicodeEncodeError, UnicodeDecodeError) as error:
        print(f"Could not communicate with the warehouse server: {error}")
        return False


if __name__ == "__main__":

    order = "Order O104 - 5 laptops"

    send_order(order)